package com.smartlect.integration;

import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderStatusLog;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderStatusLogMapper;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 订单状态历史真库回归（ADR-0005）：
 * 创建→支付→发货→退款全链留痕；CAS 并发只有胜者写日志；多子单按单写；事务回滚不写。
 */
@Testcontainers
class OrderStatusLogIT {

    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_status_log_it")
            .withUsername("smartlect")
            .withPassword("smartlect");

    private static DriverManagerDataSource dataSource;
    private static JdbcTemplate jdbc;
    private static SqlSessionTemplate sqlSessionTemplate;
    private static DataSourceTransactionManager txManager;

    private OrderStateMachine stateMachine;
    private OrderStatusLogMapper logMapper;

    @BeforeAll
    static void migrate() {
        dataSource = new DriverManagerDataSource(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(dataSource);
        Configuration configuration = new Configuration(new Environment(
                "status-log", new SpringManagedTransactionFactory(), dataSource));
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.addMapper(OrderInfoMapper.class);
        configuration.addMapper(OrderStatusLogMapper.class);
        SqlSessionFactory factory = new SqlSessionFactoryBuilder().build(configuration);
        sqlSessionTemplate = new SqlSessionTemplate(factory);
        txManager = new DataSourceTransactionManager(dataSource);
    }

    @BeforeEach
    void setUp() {
        jdbc.update("delete from order_status_log");
        jdbc.update("delete from order_info");
        stateMachine = new OrderStateMachine();
        ReflectionTestUtils.setField(stateMachine, "orderInfoMapper",
                sqlSessionTemplate.getMapper(OrderInfoMapper.class));
        ReflectionTestUtils.setField(stateMachine, "orderStatusLogMapper",
                sqlSessionTemplate.getMapper(OrderStatusLogMapper.class));
        logMapper = sqlSessionTemplate.getMapper(OrderStatusLogMapper.class);
    }

    @Test
    void fullLifecycleWritesAppendOnlyHistory() {
        jdbc.update("""
                insert into order_info(order_id, user_id, order_time, order_status, pay_order_id)
                values ('o-flow', 'u-1', now(), 0, 'po-flow')
                """);
        OrderStatusLog created = new OrderStatusLog();
        created.setOrderId("o-flow");
        created.setPayOrderId("po-flow");
        created.setToStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
        created.setEvent(OrderStateEvent.CREATE.name());
        created.setOperatorType("USER");
        created.setOperatorId("u-1");
        logMapper.insert(created);

        assertEquals(1, stateMachine.transition("o-flow", OrderStatusEnum.WAIT_PAYMENT,
                OrderStateEvent.PAY_SUCCESS));
        assertEquals(1, stateMachine.transition("o-flow", OrderStatusEnum.PAID,
                OrderStateEvent.SHIP));
        assertEquals(1, stateMachine.transition("o-flow", OrderStatusEnum.SHIPPED,
                OrderStateEvent.FULL_REFUND));

        List<OrderStatusLog> logs = logMapper.selectByOrderId("o-flow");
        assertEquals(4, logs.size());
        assertEquals(OrderStateEvent.CREATE.name(), logs.get(0).getEvent());
        assertEquals(OrderStateEvent.PAY_SUCCESS.name(), logs.get(1).getEvent());
        assertEquals(OrderStatusEnum.WAIT_PAYMENT.getStatus(), logs.get(1).getFromStatus());
        assertEquals(OrderStatusEnum.PAID.getStatus(), logs.get(1).getToStatus());
        assertEquals("po-flow", logs.get(1).getPayOrderId());
        assertEquals(OrderStateEvent.SHIP.name(), logs.get(2).getEvent());
        assertEquals(OrderStateEvent.FULL_REFUND.name(), logs.get(3).getEvent());
        assertEquals(OrderStatusEnum.REFUNDED.getStatus(), logs.get(3).getToStatus());
        assertEquals(OrderStatusEnum.REFUNDED.getStatus(),
                jdbc.queryForObject("select order_status from order_info where order_id = 'o-flow'", Integer.class));
    }

    @Test
    void concurrentCasWritesLogOnlyForWinner() throws InterruptedException {
        jdbc.update("""
                insert into order_info(order_id, user_id, order_time, order_status, pay_order_id)
                values ('o-race', 'u-1', now(), 0, 'po-race')
                """);
        int threads = 8;
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger winners = new AtomicInteger();
        List<Thread> runners = new java.util.ArrayList<>();
        for (int i = 0; i < threads; i++) {
            Thread thread = new Thread(() -> {
                try {
                    start.await();
                    if (stateMachine.transition("o-race", OrderStatusEnum.WAIT_PAYMENT,
                            OrderStateEvent.PAY_SUCCESS) > 0) {
                        winners.incrementAndGet();
                    }
                } catch (InterruptedException ignored) {
                    Thread.currentThread().interrupt();
                }
            });
            thread.start();
            runners.add(thread);
        }
        start.countDown();
        for (Thread thread : runners) {
            thread.join();
        }
        assertEquals(1, winners.get());
        assertEquals(1, logMapper.selectByOrderId("o-race").size());
    }

    @Test
    void payOrderTransitionWritesOneLogPerSubOrder() {
        jdbc.update("""
                insert into order_info(order_id, user_id, order_time, order_status, pay_order_id)
                values ('o-m1', 'u-1', now(), 0, 'po-multi'), ('o-m2', 'u-1', now(), 0, 'po-multi')
                """);
        Integer rows = new TransactionTemplate(txManager).execute(status ->
                stateMachine.transitionPayOrder("po-multi", OrderStatusEnum.WAIT_PAYMENT,
                        OrderStateEvent.USER_CANCEL));
        assertEquals(2, rows);
        assertEquals(1, logMapper.selectByOrderId("o-m1").size());
        assertEquals(1, logMapper.selectByOrderId("o-m2").size());
        assertEquals(OrderStatusEnum.CANCELLED.getStatus(),
                logMapper.selectByOrderId("o-m2").get(0).getToStatus());
        assertEquals("po-multi", logMapper.selectByOrderId("o-m2").get(0).getPayOrderId());
    }

    @Test
    void rolledBackTransactionLeavesNeitherStatusNorLog() {
        jdbc.update("""
                insert into order_info(order_id, user_id, order_time, order_status, pay_order_id)
                values ('o-rollback', 'u-1', now(), 0, 'po-rollback')
                """);
        new TransactionTemplate(txManager).executeWithoutResult(status -> {
            stateMachine.transition("o-rollback", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAY_SUCCESS);
            status.setRollbackOnly();
        });
        assertEquals(0, jdbc.queryForObject(
                "select order_status from order_info where order_id = 'o-rollback'", Integer.class));
        assertTrue(logMapper.selectByOrderId("o-rollback").isEmpty());
    }
}
