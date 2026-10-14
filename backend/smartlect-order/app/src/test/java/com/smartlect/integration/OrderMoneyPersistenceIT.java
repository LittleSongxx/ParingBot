package com.smartlect.integration;

import com.smartlect.biz.RefundSagaService;
import com.smartlect.biz.RefundSagaTransactionService;
import com.smartlect.biz.impl.OrderInfoServiceImpl;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.RefundRequestMapper;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.sql.SQLException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Real Smartlect Flyway schema and MyBatis mappings; external cash/stock effects remain mocked. */
@Testcontainers
@SuppressWarnings("unchecked")
class OrderMoneyPersistenceIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_money_it").withUsername("smartlect").withPassword("smartlect");
    private static SqlSessionFactory sessions;

    @BeforeAll
    static void migrate() {
        var dataSource = new UnpooledDataSource("com.mysql.cj.jdbc.Driver", MYSQL.getJdbcUrl(),
                MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration").load().migrate();
        Configuration config = new Configuration(new Environment("money", new JdbcTransactionFactory(), dataSource));
        config.setMapUnderscoreToCamelCase(true);
        config.addMapper(OrderItemMapper.class);
        config.addMapper(OrderInfoMapper.class);
        config.addMapper(RefundRequestMapper.class);
        sessions = new SqlSessionFactoryBuilder().build(config);
    }

    @Test
    void discountedRefundReloadsPersistedPaidAmountAndNeverAddsCashTwice() {
        try (SqlSession session = sessions.openSession(false)) {
            OrderInfo order = seed(session, "discount", "90.00");
            allocate(session, order);
            session.commit();
        }
        try (SqlSession session = sessions.openSession(false)) {
            OrderItemMapper<OrderItem, OrderItemQuery> items = session.getMapper(OrderItemMapper.class);
            OrderItem line = items.selectByOrderItemId("discount-item");
            assertEquals(new BigDecimal("100.00"), line.getItemAmount());
            assertEquals(new BigDecimal("90.00"), line.getPaidAmount());
            assertEquals(new BigDecimal("0.00"), line.getRefundedAmount());
            var mq = mock(TransactionalMqSender.class);
            RefundSagaTransactionService service = refunds(session, mq);
            RefundRequest request = service.createOrLoad("discount-item", "user-1");
            assertEquals(new BigDecimal("90.00"), request.getRefundAmount());
            assertEquals(request.getRefundRequestId(), service.createOrLoad("discount-item", "user-1").getRefundRequestId());
            service.markPaymentConfirmed(request.getRefundRequestId());
            assertTrue(service.queueStockRestore(request.getRefundRequestId(), false));
            assertFalse(service.queueStockRestore(request.getRefundRequestId(), false));
            session.commit();
            line = items.selectByOrderItemId("discount-item");
            assertEquals(new BigDecimal("90.00"), line.getRefundedAmount());
            assertEquals(new BigDecimal("0.00"), line.getRemainingRefundableAmount());
            verify(mq, times(1)).sendAfterCommit(any(), any(), any(), any(), any(), any());
        }
    }

    @Test
    void zeroPaidLineReturnsStockWithoutCallingCashChannel() {
        try (SqlSession session = sessions.openSession(false)) {
            OrderInfo order = seed(session, "free", "0.00");
            allocate(session, order);
            var mq = mock(TransactionalMqSender.class);
            RefundSagaTransactionService transaction = refunds(session, mq);
            RefundRequest request = transaction.createOrLoad("free-item", "user-1");
            assertEquals(new BigDecimal("0.00"), request.getRefundAmount());
            assertEquals("PAYMENT_CONFIRMED", request.getStatus());
            var pay = mock(PayFeignSupport.class);
            var saga = new RefundSagaService();
            ReflectionTestUtils.setField(saga, "transactionService", transaction);
            ReflectionTestUtils.setField(saga, "payFeignSupport", pay);
            OrderItemMapper<OrderItem, OrderItemQuery> items = session.getMapper(OrderItemMapper.class);
            saga.requestRefund(items.selectByOrderItemId("free-item"), "user-1");
            session.commit();
            verifyNoInteractions(pay);
            verify(mq, times(1)).sendAfterCommit(any(), any(), any(), any(), any(), any());
        }
    }

    @Test
    void failedPaymentTransactionRollsBackAllocationAndSqlRejectsOverRefunds() throws Exception {
        try (SqlSession session = sessions.openSession(false)) {
            OrderInfo order = seed(session, "rollback", "90.00");
            session.commit();
            allocate(session, order);
            session.rollback();
            OrderItemMapper<OrderItem, OrderItemQuery> items = session.getMapper(OrderItemMapper.class);
            assertNull(items.selectByOrderItemId("rollback-item").getPaidAmount());
            assertThrows(BusinessException.class, () -> refunds(session, mock(TransactionalMqSender.class))
                    .createOrLoad("rollback-item", "user-1"));
            try (var statement = session.getConnection().createStatement()) {
                assertThrows(SQLException.class, () -> statement.executeUpdate(
                        "UPDATE order_item SET refunded_amount=1 WHERE order_item_id='rollback-item'"));
                allocate(session, order);
                assertThrows(SQLException.class, () -> statement.executeUpdate(
                        "UPDATE order_item SET refunded_amount=100 WHERE order_item_id='rollback-item'"));
            }
            session.rollback();
        }
    }

    @Test
    void quoteConsumptionRollsBackAndSurvivesReconstructionOnlyAfterCommit() {
        var source = sessions.getConfiguration().getEnvironment().getDataSource();
        var jdbc = new org.springframework.jdbc.core.JdbcTemplate(source);
        var transaction = new org.springframework.transaction.support.TransactionTemplate(
                new org.springframework.jdbc.datasource.DataSourceTransactionManager(source));
        var quotes = new com.smartlect.biz.OrderQuoteService(jdbc,
                new org.springframework.jdbc.datasource.DataSourceTransactionManager(source));
        var input = new com.smartlect.biz.OrderQuoteService.Input("mock", "quote-address", 0, null,
                List.of(new com.smartlect.biz.OrderQuoteService.Line("quote-product", "v1", 1, null)));
        var order = com.smartlect.biz.OrderQuoteService.normalize(input);
        var address = new com.smartlect.api.vo.UserAddressVO();
        address.setAddress("synthetic-address");
        OrderItem item = new OrderItem();
        item.setProductId("quote-product");
        item.setPropertyValueIdHash("quote-sku");
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("10.00"));
        var issued = quotes.issue("quote-user", order, address, List.of(item), new BigDecimal("10.00"));
        String quoteId = (String) issued.get("quoteId");
        assertThrows(IllegalStateException.class, () -> transaction.executeWithoutResult(status -> {
            var quote = quotes.lock("quote-user", quoteId);
            quotes.validate(quote, "quote-user", order, 1000L, address, List.of(item), new BigDecimal("10.00"));
            quotes.consume(quote, "quote-pay-rollback");
            throw new IllegalStateException("fail after quote consumption");
        }));
        assertNull(jdbc.queryForObject("SELECT pay_order_id FROM order_quote WHERE quote_id=?", String.class, quoteId));
        transaction.executeWithoutResult(status -> quotes.consume(quotes.lock("quote-user", quoteId), "quote-pay-committed"));
        var restarted = new com.smartlect.biz.OrderQuoteService(new org.springframework.jdbc.core.JdbcTemplate(source),
                new org.springframework.jdbc.datasource.DataSourceTransactionManager(source));
        var used = assertThrows(com.smartlect.exception.HttpBusinessException.class,
                () -> transaction.execute(status -> restarted.lock("quote-user", quoteId)));
        assertEquals("QUOTE_ALREADY_CONSUMED", used.getMessage());
        assertThrows(com.smartlect.exception.HttpBusinessException.class,
                () -> transaction.execute(status -> restarted.lock("another-user", quoteId)));
    }

    private static OrderInfo seed(SqlSession session, String id, String paid) {
        OrderInfo order = new OrderInfo();
        order.setOrderId(id);
        order.setPayOrderId(id + "-pay");
        order.setUserId("user-1");
        order.setOrderStatus(1);
        order.setAmount(new BigDecimal(paid));
        order.setPayChannel("mock");
        OrderInfoMapper<OrderInfo, OrderInfoQuery> orders = session.getMapper(OrderInfoMapper.class);
        orders.insert(order);
        OrderItem item = new OrderItem();
        item.setOrderItemId(id + "-item");
        item.setOrderId(id);
        item.setProductId("product-1");
        item.setPropertyValueIdHash("sku-1");
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("100.00"));
        item.setOrderItemStatus(1);
        OrderItemMapper<OrderItem, OrderItemQuery> items = session.getMapper(OrderItemMapper.class);
        items.insertBatch(List.of(item));
        return order;
    }

    private static void allocate(SqlSession session, OrderInfo order) {
        var service = new OrderInfoServiceImpl();
        ReflectionTestUtils.setField(service, "orderItemMapper", session.getMapper(OrderItemMapper.class));
        ReflectionTestUtils.invokeMethod(service, "recordPaymentOutcomes", List.of(order), order.getPayOrderId());
    }

    private static RefundSagaTransactionService refunds(SqlSession session, TransactionalMqSender mq) {
        var service = new RefundSagaTransactionService();
        ReflectionTestUtils.setField(service, "orderItemMapper", session.getMapper(OrderItemMapper.class));
        ReflectionTestUtils.setField(service, "orderInfoMapper", session.getMapper(OrderInfoMapper.class));
        ReflectionTestUtils.setField(service, "refundRequestMapper", session.getMapper(RefundRequestMapper.class));
        ReflectionTestUtils.setField(service, "transactionalMqSender", mq);
        // finalizeOrderRefund 走状态机 CAS 翻单（FULL/PARTIAL_REFUND），
        // 真库装配需要补挂真实 mapper 的状态机（曾因服务新增该依赖而漏注入）。
        var machine = new com.smartlect.state.OrderStateMachine();
        ReflectionTestUtils.setField(machine, "orderInfoMapper", session.getMapper(OrderInfoMapper.class));
        ReflectionTestUtils.setField(service, "orderStateMachine", machine);
        return service;
    }
}
