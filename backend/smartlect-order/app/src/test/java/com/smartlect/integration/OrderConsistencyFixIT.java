package com.smartlect.integration;

import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.biz.OrderQuoteService;
import com.smartlect.biz.OrderRequestIdempotencyService;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.mappers.OrderRequestIdempotencyMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 批次一 P0 一致性修复的真库回归（ADR-0001）：
 * 1) quote claim-first——并发占用恰好一个赢家、失败释放后可重新占用；
 * 2) 幂等账本 REQUIRES_NEW——外层事务回滚后 FAILED 留痕仍独立提交。
 */
@Testcontainers
class OrderConsistencyFixIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_consistency_it").withUsername("smartlect").withPassword("smartlect");

    private static DriverManagerDataSource dataSource;
    private static JdbcTemplate jdbc;
    private static SqlSessionTemplate sqlSessionTemplate;

    private OrderQuoteService quotes;
    private OrderRequestIdempotencyService ledger;
    private PlatformTransactionManager txManager;

    @BeforeAll
    static void migrate() {
        dataSource = new DriverManagerDataSource(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(dataSource);
        // SqlSessionTemplate 要求工厂使用 SpringManagedTransactionFactory，
        // mapper 调用才能加入 Spring 事务同步（REQUIRES_NEW 语义的前提）。
        Configuration config = new Configuration(
                new Environment("consistency",
                        new org.mybatis.spring.transaction.SpringManagedTransactionFactory(), dataSource));
        config.setMapUnderscoreToCamelCase(true);
        config.addMapper(OrderRequestIdempotencyMapper.class);
        SqlSessionFactory factory = new SqlSessionFactoryBuilder().build(config);
        // SqlSessionTemplate 让 mapper 调用参与 Spring 事务同步（REQUIRES_NEW 语义的前提）
        sqlSessionTemplate = new SqlSessionTemplate(factory);
    }

    @BeforeEach
    void setUp() {
        jdbc.update("DELETE FROM order_quote");
        jdbc.update("DELETE FROM order_request_idempotency");
        txManager = new DataSourceTransactionManager(dataSource);
        quotes = new OrderQuoteService(jdbc, txManager);
        ledger = new OrderRequestIdempotencyService(
                txManager, sqlSessionTemplate.getMapper(OrderRequestIdempotencyMapper.class),
                new com.smartlect.metrics.SmartlectMetrics(new io.micrometer.core.instrument.simple.SimpleMeterRegistry()));
    }

    @Test
    void concurrentClaimsAllowExactlyOneWinner() throws InterruptedException {
        PostOrderDTO order = order();
        String quoteId = issueQuote(order, "user-1");
        int threads = 4;
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger wins = new AtomicInteger();
        AtomicInteger conflicts = new AtomicInteger();
        AtomicReference<RuntimeException> unexpected = new AtomicReference<>();
        List<Thread> runners = new java.util.ArrayList<>();
        for (int i = 0; i < threads; i++) {
            final String payOrderId = "pay-claim-" + i;
            Thread thread = new Thread(() -> {
                try {
                    start.await();
                    quotes.claim("user-1", quoteId, payOrderId, order, 1000L);
                    wins.incrementAndGet();
                } catch (HttpBusinessException conflict) {
                    if (conflict.getHttpStatus() == 409) {
                        conflicts.incrementAndGet();
                    } else {
                        unexpected.compareAndSet(null, conflict);
                    }
                } catch (InterruptedException ignored) {
                    Thread.currentThread().interrupt();
                } catch (RuntimeException other) {
                    unexpected.compareAndSet(null, other);
                }
            });
            thread.start();
            runners.add(thread);
        }
        start.countDown();
        for (Thread thread : runners) {
            thread.join(30_000);
        }
        assertNull(unexpected.get(), "claim 不应产生 409 之外的失败");
        assertEquals(1, wins.get(), "并发 claim 必须恰好一个赢家");
        assertEquals(threads - 1, conflicts.get());
        assertNotNull(jdbc.queryForObject(
                "SELECT pay_order_id FROM order_quote WHERE quote_id=?", String.class, quoteId));
    }

    @Test
    void releasedQuoteCanBeClaimedAgainByNewRequest() {
        PostOrderDTO order = order();
        String quoteId = issueQuote(order, "user-1");
        quotes.claim("user-1", quoteId, "pay-first", order, 1000L);
        // 建单失败路径：释放占用后，报价可被下一个请求重新占用
        assertTrue(quotes.release(quoteId, "user-1", "pay-first"));
        assertNull(jdbc.queryForObject(
                "SELECT pay_order_id FROM order_quote WHERE quote_id=?", String.class, quoteId));
        quotes.claim("user-1", quoteId, "pay-second", order, 1000L);
        // claim 返回的 Quote 是占用前加载的（payOrderId 为空），占用结果以库为准
        assertEquals("pay-second", jdbc.queryForObject(
                "SELECT pay_order_id FROM order_quote WHERE quote_id=?", String.class, quoteId));
        // 释放必须校验占用者：他人占用时释放不生效
        assertFalse(quotes.release(quoteId, "user-1", "pay-first"));
        assertEquals("pay-second", jdbc.queryForObject(
                "SELECT pay_order_id FROM order_quote WHERE quote_id=?", String.class, quoteId));
    }

    @Test
    void failedCommandLedgerSurvivesOuterTransactionRollback() {
        // 旧缺陷：台账写在外层事务里（REQUIRED 传播），秒杀类 @Transactional 调用方回滚时
        // "请求已受理/已失败"留痕一并消失。REQUIRES_NEW 后 FAILED 必须独立提交。
        TransactionTemplate outer = new TransactionTemplate(txManager);
        outer.executeWithoutResult(status -> {
            try {
                ledger.execute("user-1", OrderRequestIdempotencyService.COMMAND_POST_ORDER,
                        "ledger-key-00000001", Map.of("addressId", "a1"), Object.class,
                        () -> { throw new HttpBusinessException(600, "模拟建单失败"); });
            } catch (HttpBusinessException expected) {
                // 命令失败路径正是被测对象
            }
            status.setRollbackOnly();
        });

        OrderRequestIdempotency row = ledger.find("user-1",
                OrderRequestIdempotencyService.COMMAND_POST_ORDER, "ledger-key-00000001");
        assertNotNull(row, "外层回滚后 FAILED 台账必须留痕");
        assertEquals("FAILED", row.getStatus());

        // 同键重放：得到确定性的失败回放，而不是凭空重新执行
        HttpBusinessException replay = assertThrows(HttpBusinessException.class,
                () -> ledger.execute("user-1", OrderRequestIdempotencyService.COMMAND_POST_ORDER,
                        "ledger-key-00000001", Map.of("addressId", "a1"), Object.class,
                        () -> { throw new AssertionError("FAILED 台账不允许重执行"); }));
        assertEquals(409, replay.getHttpStatus());
        assertTrue(replay.getMessage().contains("模拟建单失败"));
    }

    private String issueQuote(PostOrderDTO order, String userId) {
        OrderItem item = new OrderItem();
        item.setProductId("p1");
        item.setPropertyValueIdHash("hash-1");
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("10.00"));
        UserAddressVO address = new UserAddressVO();
        address.setAddress("上海市");
        address.setAddressee("收件人");
        address.setPhone("13800000000");
        Map<String, Object> issued = quotes.issue(userId, order, address, List.of(item), new BigDecimal("10.00"));
        return (String) issued.get("quoteId");
    }

    private static PostOrderDTO order() {
        return OrderQuoteService.normalize(new OrderQuoteService.Input(
                "mock", "a1", 0, null,
                List.of(new OrderQuoteService.Line("p1", "v1", 1, null))));
    }
}
