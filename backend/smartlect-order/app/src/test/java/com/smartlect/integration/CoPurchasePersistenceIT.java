package com.smartlect.integration;

import com.smartlect.controller.internal.OrderCommerceInternalController;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.mappers.OrderItemMapper;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.session.SqlSessionFactoryBuilder;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

@Testcontainers
@SuppressWarnings("unchecked")
class CoPurchasePersistenceIT {
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4.11")
            .withDatabaseName("smartlect_copurchase_it").withUsername("smartlect").withPassword("smartlect");
    private static SqlSessionFactory sessions;

    @BeforeAll
    static void migrate() {
        var dataSource = new UnpooledDataSource("com.mysql.cj.jdbc.Driver", MYSQL.getJdbcUrl(),
                MYSQL.getUsername(), MYSQL.getPassword());
        Flyway.configure().dataSource(dataSource).locations("classpath:db/migration").load().migrate();
        Configuration config = new Configuration(new Environment("copurchase", new JdbcTransactionFactory(), dataSource));
        config.setMapUnderscoreToCamelCase(true);
        config.addMapper(OrderItemMapper.class);
        sessions = new SqlSessionFactoryBuilder().build(config);
    }

    @BeforeEach
    void resetFixture() throws SQLException {
        try (SqlSession session = sessions.openSession(true); var statement = session.getConnection().createStatement()) {
            statement.executeUpdate("DELETE FROM order_item");
            statement.executeUpdate("DELETE FROM order_info");
            statement.executeUpdate("DELETE FROM refund_request");
        }
    }

    @Test
    void paidPaymentFindsOtherProductsAcrossSplitChildOrders() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "one", "pay-1", "p2");
            assertEquals(List.of("p2"), query(session, 5));
        }
    }

    @Test
    void frequencyCountsPaymentGroupsRatherThanSkuRowsOrQuantities() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "many", "pay-1", "p2");
            item(session, "many-seed-extra", "many-seed", "p1", BigDecimal.TEN);
            item(session, "many-candidate-extra", "many-candidate", "p2", BigDecimal.TEN);
            update(session, "UPDATE order_item SET buy_count=50 WHERE order_id='many-candidate'");
            pair(session, "second", "pay-2", "p3");
            pair(session, "third", "pay-3", "p3");
            assertEquals(List.of("p3", "p2"), query(session, 5));
        }
    }

    @Test
    void refundedSeedOrCandidateIsExcludedButSurvivingPartialRefundLinesRemain() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "seedref", "pay-1", "p2");
            update(session, "UPDATE order_item SET order_item_status=0,refunded_amount=paid_amount WHERE order_id='seedref-seed'");
            pair(session, "candref", "pay-2", "p3");
            update(session, "UPDATE order_item SET order_item_status=0,refunded_amount=paid_amount WHERE order_id='candref-candidate'");
            pair(session, "partial", "pay-3", "p4");
            item(session, "partial-seed-refund", "partial-seed", "p1", BigDecimal.TEN);
            item(session, "partial-cand-refund", "partial-candidate", "p4", BigDecimal.TEN);
            update(session, "UPDATE order_item SET order_item_status=0,refunded_amount=paid_amount WHERE order_item_id IN ('partial-seed-refund','partial-cand-refund')");
            update(session, "UPDATE order_info SET order_status=7");
            assertEquals(List.of("p4"), query(session, 5));
        }
    }

    @Test
    void unpaidCancelledClosedDeletedOrFullyRefundedChildOrdersCannotContribute() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            for (int status : new int[]{0, 4, 5, -1, 6}) {
                String seed = "s" + status;
                pair(session, seed, "seed-pay-" + status, "p2");
                update(session, "UPDATE order_info SET order_status=? WHERE order_id=?", status, seed + "-seed");
                String candidate = "c" + status;
                pair(session, candidate, "candidate-pay-" + status, "p3");
                update(session, "UPDATE order_info SET order_status=? WHERE order_id=?", status, candidate + "-candidate");
            }
            assertEquals(List.of(), query(session, 5));
        }
    }

    @Test
    void onlyConfirmedLinesContributeAndZeroPaidConfirmedProductsRemainEligible() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "snull", "pay-1", "p2");
            update(session, "UPDATE order_item SET paid_amount=NULL WHERE order_id='snull-seed'");
            pair(session, "cnull", "pay-2", "p3");
            update(session, "UPDATE order_item SET paid_amount=NULL WHERE order_id='cnull-candidate'");
            order(session, "zero-seed", "pay-zero", "u1");
            order(session, "zero-candidate", "pay-zero", "u1");
            item(session, "zero-seed-item", "zero-seed", "p1", BigDecimal.ZERO);
            item(session, "zero-candidate-item", "zero-candidate", "p4", BigDecimal.ZERO);
            update(session, "UPDATE order_info SET amount=0,order_status=3 WHERE pay_order_id='pay-zero'");
            assertEquals(List.of("p4"), query(session, 5));
        }
    }

    @Test
    void paymentMustBePresentAndSharedByTheSameUser() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "other", "pay-1", "p2");
            update(session, "UPDATE order_info SET user_id='u2' WHERE order_id='other-candidate'");
            pair(session, "blank", "", "p3");
            pair(session, "absent", null, "p4");
            assertEquals(List.of(), query(session, 5));
        }
    }

    @Test
    void tiesHaveStableProductOrderingAndLimitIsClamped() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "first", "pay-1", "p3");
            pair(session, "second", "pay-2", "p2");
            assertEquals(List.of("p2", "p3"), query(session, 5));
            assertEquals(List.of("p2"), query(session, 0));
        }
    }

    @Test
    void popularityCountsConfirmedQuantityIncludingZeroPaymentAndExcludingRefund() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            order(session, "paid", "pay-paid", "u1");
            item(session, "paid-line", "paid", "p1", BigDecimal.TEN);
            update(session, "UPDATE order_item SET buy_count=2 WHERE order_id='paid'");
            order(session, "unpaid", "pay-unpaid", "u1");
            item(session, "unpaid-line", "unpaid", "p2", null);
            update(session, "UPDATE order_info SET order_status=0 WHERE order_id='unpaid'");
            update(session, "UPDATE order_item SET buy_count=99 WHERE order_id='unpaid'");
            order(session, "zero", "pay-zero", "u1");
            item(session, "zero-line", "zero", "p3", BigDecimal.ZERO);
            update(session, "UPDATE order_info SET amount=0 WHERE order_id='zero'");
            update(session, "UPDATE order_item SET buy_count=3 WHERE order_id='zero'");
            order(session, "refunded", "pay-refunded", "u1");
            item(session, "refunded-line", "refunded", "p4", BigDecimal.TEN);
            update(session, "UPDATE order_item SET buy_count=4,order_item_status=0,refunded_amount=paid_amount WHERE order_id='refunded'");
            update(session, "UPDATE order_info SET order_status=6 WHERE order_id='refunded'");
            update(session, """
                    INSERT INTO refund_request(refund_request_id,refund_order_no,source_pay_order_id,order_id,
                        order_item_id,user_id,product_id,property_value_id_hash,buy_count,refund_amount,status,completed_at)
                    VALUES ('refund-1','refund-1','pay-refunded','refunded','refunded-line','u1','p4','refunded-line',4,10,'COMPLETED',NOW())
                    """);
            var result = popular(session, Map.of("limit", 20));
            // 现行口径（basis=confirmed_payment_units_excluding_refunds）：
            // 0 元支付单（p3）计入确认数量；整单退款（p4，refunded_amount=paid_amount
            // 且 order_status=6）被排除。本用例曾按"退款计入"断言，随 SQL 口径演进已陈旧。
            assertEquals(List.of("p3", "p1"), result.stream().map(r -> r.get("productId")).toList());
            assertEquals(List.of(3L, 2L), result.stream().map(r -> r.get("paidUnits")).toList());
            assertEquals(List.of("confirmed_payment_units_excluding_refunds"), result.stream().map(r -> r.get("basis")).distinct().toList());
        }
    }

    @Test
    void popularityRejectsAbsentOrConflictingPaymentOwnersAndInvalidQuantity() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            for (String id : List.of("blank-pay", "blank-owner", "conflict", "zero-quantity", "valid")) {
                order(session, id, id.equals("blank-pay") ? "" : "pay-" + id,
                        id.equals("blank-owner") ? null : "u1");
                item(session, id + "-line", id, "p-" + id, BigDecimal.TEN);
            }
            order(session, "conflicting-owner", "pay-conflict", "u2");
            update(session, "UPDATE order_item SET buy_count=0 WHERE order_id='zero-quantity'");
            assertEquals(List.of("p-valid"), popular(session, Map.of()).stream().map(r -> r.get("productId")).toList());
        }
    }

    @Test
    void popularAndCoPurchaseApplyScopeBeforeLimitAndUseStableTies() throws Exception {
        try (SqlSession session = sessions.openSession(true)) {
            pair(session, "first", "pay-first", "p2");
            pair(session, "second", "pay-second", "p3");
            assertEquals(List.of("p1"), popular(session, Map.of("limit", 1)).stream().map(r -> r.get("productId")).toList());
            assertEquals(List.of("p2", "p3"), popular(session, Map.of("excludeProductIds", List.of("p1")))
                    .stream().map(r -> r.get("productId")).toList());
            assertEquals(List.of("p3"), popular(session, Map.of("productIds", List.of("p3"), "limit", 1))
                    .stream().map(r -> r.get("productId")).toList());
            assertEquals(List.of("p3"), popular(session, Map.of("excludeProductIds", List.of("p1", "p2"), "limit", 1))
                    .stream().map(r -> r.get("productId")).toList());
            assertEquals(List.of(), popular(session, Map.of("productIds", List.of())));
            var controller = controller(session);
            assertEquals(List.of("p3"), controller.coPurchaseProductIds(Map.of("productId", "p1", "limit", 1,
                    "productIds", List.of("p3"))).getData());
            assertEquals(List.of("p3"), controller.coPurchaseProductIds(Map.of("productId", "p1", "limit", 1,
                    "excludeProductIds", List.of("p2"))).getData());
        }
    }

    private static void update(SqlSession session, String sql, Object... values) throws SQLException {
        try (var statement = session.getConnection().prepareStatement(sql)) {
            for (int index = 0; index < values.length; index++) statement.setObject(index + 1, values[index]);
            statement.executeUpdate();
            session.clearCache();
        }
    }

    private static void pair(SqlSession session, String prefix, String payId, String candidate) throws SQLException {
        order(session, prefix + "-seed", payId, "u1");
        order(session, prefix + "-candidate", payId, "u1");
        item(session, prefix + "-seed-item", prefix + "-seed", "p1", new BigDecimal("10.00"));
        item(session, prefix + "-candidate-item", prefix + "-candidate", candidate, new BigDecimal("10.00"));
    }

    private static void order(SqlSession session, String id, String payId, String userId) throws SQLException {
        try (var statement = session.getConnection().prepareStatement(
                "INSERT INTO order_info(order_id,pay_order_id,user_id,order_status,amount) VALUES (?,?,?,1,10.00)")) {
            statement.setString(1, id);
            statement.setString(2, payId);
            statement.setString(3, userId);
            statement.executeUpdate();
        }
    }

    private static void item(SqlSession session, String id, String orderId, String productId, BigDecimal paid) {
        OrderItem line = new OrderItem();
        line.setOrderItemId(id);
        line.setOrderId(orderId);
        line.setProductId(productId);
        line.setPropertyValueIdHash(id);
        line.setBuyCount(1);
        line.setItemAmount(new BigDecimal("10.00"));
        line.setOrderItemStatus(1);
        OrderItemMapper<OrderItem, OrderItemQuery> mapper = session.getMapper(OrderItemMapper.class);
        mapper.insert(line);
        if (paid != null) assertEquals(1, mapper.recordPaidAmount(id, paid));
    }

    private static List<String> query(SqlSession session, int limit) {
        return controller(session).coPurchaseProductIds(Map.of("productId", "p1", "limit", limit)).getData();
    }

    private static List<Map<String, Object>> popular(SqlSession session, Map<String, Object> body) {
        return controller(session).popularProducts(body).getData();
    }

    private static OrderCommerceInternalController controller(SqlSession session) {
        // 控制器不再直连 mapper：聚合查询经 OrderItemService（真实实现 + 真库 mapper）
        var itemService = new com.smartlect.biz.impl.OrderItemServiceImpl();
        ReflectionTestUtils.setField(itemService, "orderItemMapper", session.getMapper(OrderItemMapper.class));
        var controller = new OrderCommerceInternalController();
        ReflectionTestUtils.setField(controller, "orderItemService", itemService);
        return controller;
    }
}
