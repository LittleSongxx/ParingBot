package com.smartlect.biz.impl;

import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.enums.LogisticsStatusEnum;
import com.smartlect.api.enums.OrderFromTypeEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.api.support.ProductFeignSupport;
import com.smartlect.api.support.StockFeignSupport;
import com.smartlect.api.support.UserFeignSupport;
import com.smartlect.api.vo.ProductInfoSnapshotVO;
import com.smartlect.api.vo.ProductPropertyValueSnapshotVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.dto.LogisticsSendDTO;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderCreationIntegrityTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    @Mock
    private OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;
    @Mock
    private ProductFeignSupport productFeignSupport;
    @Mock
    private StockFeignSupport stockFeignSupport;
    @Mock
    private UserFeignSupport userFeignSupport;
    @Mock
    private RedisComponent redisComponent;
    @Mock
    private PayFeignSupport payFeignSupport;
    @Mock
    private TransactionalMqSender transactionalMqSender;

    @Mock
    private com.smartlect.biz.OrderRequestIdempotencyService orderRequestIdempotencyService;
    @Mock
    private com.smartlect.biz.OrderQuoteService orderQuoteService;
    @Mock
    private com.smartlect.api.support.CouponFeignSupport couponFeignSupport;
    @Mock
    private com.smartlect.mappers.OrderCouponRelMapper<com.smartlect.entity.po.OrderCouponRel,
            com.smartlect.entity.query.OrderCouponRelQuery> orderCouponRelMapper;
    @Mock
    private com.smartlect.component.RemoteCompensateRecorder remoteCompensateRecorder;

    @Mock
    private org.springframework.transaction.support.TransactionTemplate transactionTemplate;

    @InjectMocks
    private OrderInfoServiceImpl service;

    @org.junit.jupiter.api.BeforeEach
    void setUpTransactionTemplate() {
        // Phase 3 短事务透传：让 lambda 内的 mapper 调用直接执行
        org.mockito.Mockito.lenient()
                .doAnswer(call -> {
                    java.util.function.Consumer<org.springframework.transaction.TransactionStatus> cb = call.getArgument(0);
                    cb.accept(null);
                    return null;
                })
                .when(transactionTemplate)
                .executeWithoutResult(org.mockito.ArgumentMatchers.<java.util.function.Consumer<org.springframework.transaction.TransactionStatus>>any());
    }

    @Test
    void authoritativeSkuDrivesStockAndEveryOrderGetsLogistics() {
        ProductItem first = item("p1", "v1", "forged-hash-1");
        ProductItem second = item("p2", "v2", "forged-hash-2");
        PostOrderDTO request = request(List.of(first, second));
        ProductSnapshotBatchVO snapshot = new ProductSnapshotBatchVO();

        when(userFeignSupport.getAddress("address-1", "user-1")).thenReturn(address());
        when(productFeignSupport.snapshotBatch(List.of("p1", "p2"))).thenReturn(snapshot);
        when(productFeignSupport.toProductInfoMap(snapshot)).thenReturn(Map.of(
                "p1", product("p1", "Headphones"),
                "p2", product("p2", "Coat")));
        when(productFeignSupport.toPropertyValueMap(snapshot)).thenReturn(Map.of(
                "p1v1", property("p1", "v1"),
                "p2v2", property("p2", "v2")));
        when(productFeignSupport.toSkuMapByPropertyValueIds(snapshot)).thenReturn(Map.of(
                "p1v1", sku("p1", "v1", "trusted-hash-1", "10.00"),
                "p2v2", sku("p2", "v2", "trusted-hash-2", "20.00")));
        when(stockFeignSupport.getAvailable("p1", "trusted-hash-1")).thenReturn(10);
        when(stockFeignSupport.getAvailable("p2", "trusted-hash-2")).thenReturn(10);
        when(redisComponent.getLogisticsInfo()).thenReturn(sender());

        ReflectionTestUtils.invokeMethod(service, "createOrder", "user-1", request);

        verify(stockFeignSupport, never()).getAvailable("p1", "forged-hash-1");
        verify(stockFeignSupport, never()).getAvailable("p2", "forged-hash-2");
        assertEquals("trusted-hash-1", first.getPropertyValueIdHash());
        assertEquals("trusted-hash-2", second.getPropertyValueIdHash());

        ArgumentCaptor<List<ProductItem>> stockCaptor = listCaptor();
        verify(stockFeignSupport).changeStockBatch(stockCaptor.capture(), org.mockito.ArgumentMatchers.anyString());
        assertEquals(Set.of("trusted-hash-1", "trusted-hash-2"), hashes(stockCaptor.getValue()));

        ArgumentCaptor<List<OrderInfo>> orderCaptor = listCaptor();
        ArgumentCaptor<List<OrderItem>> itemCaptor = listCaptor();
        ArgumentCaptor<List<OrderLogisticsInfo>> logisticsCaptor = listCaptor();
        verify(orderInfoMapper).insertBatch(orderCaptor.capture());
        verify(orderItemMapper).insertBatch(itemCaptor.capture());
        verify(orderLogisticsInfoMapper).insertBatch(logisticsCaptor.capture());

        List<OrderInfo> orders = orderCaptor.getValue();
        List<OrderLogisticsInfo> logistics = logisticsCaptor.getValue();
        assertEquals(2, orders.size());
        assertEquals(2, logistics.size());
        assertEquals(
                orders.stream().map(OrderInfo::getOrderId).collect(Collectors.toSet()),
                logistics.stream().map(OrderLogisticsInfo::getOrderId).collect(Collectors.toSet()));
        assertEquals(Set.of(OrderStatusEnum.WAIT_PAYMENT.getStatus()),
                orders.stream().map(OrderInfo::getOrderStatus).collect(Collectors.toSet()));
        assertEquals(Set.of(LogisticsStatusEnum.PENDING_SHIPMENT.getStatus()),
                logistics.stream().map(OrderLogisticsInfo::getLogisticsStatus).collect(Collectors.toSet()));
        assertEquals(Set.of("Shanghai"),
                logistics.stream().map(OrderLogisticsInfo::getReceiverAddress).collect(Collectors.toSet()));
        assertEquals(Set.of("Warehouse"),
                logistics.stream().map(OrderLogisticsInfo::getSenderAddress).collect(Collectors.toSet()));
        assertEquals(Set.of("trusted-hash-1", "trusted-hash-2"),
                itemCaptor.getValue().stream()
                        .map(OrderItem::getPropertyValueIdHash)
                        .collect(Collectors.toSet()));
    }

    @Test
    void confirmedOrderReplayDoesNotReloadExpiredQuoteOrMutateBusiness() {
        PostOrderDTO request = request(List.of(item("p1", "v1", "ignored")));
        com.smartlect.api.dto.PayInfoDTO replay = new com.smartlect.api.dto.PayInfoDTO(null, "original-pay", new BigDecimal("10.00"));
        replay.setIdempotencyReplayed(true);
        when(orderRequestIdempotencyService.execute(org.mockito.ArgumentMatchers.eq("user-1"),
                org.mockito.ArgumentMatchers.eq(com.smartlect.biz.OrderRequestIdempotencyService.COMMAND_POST_ORDER_V2),
                org.mockito.ArgumentMatchers.eq("original-command-key"), org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.eq(com.smartlect.api.dto.PayInfoDTO.class), org.mockito.ArgumentMatchers.any()))
                .thenReturn(replay);
        assertEquals("original-pay", service.createConfirmed("user-1", request, "a".repeat(32), 1000L,
                "original-command-key").getPayOrderId());
        org.mockito.Mockito.verifyNoInteractions(orderQuoteService, productFeignSupport, stockFeignSupport,
                couponFeignSupport, payFeignSupport, userFeignSupport);
    }

    @Test
    void actualSkuRepricingAfterIssuedQuoteIsRejectedByRealQuoteValidator() {
        // Current service integration with fake provider/SQL ports; this is not an HTTP repricing result.
        PostOrderDTO request = request(List.of(item("p1", "v1", "ignored")));
        request.setPayMethod("mock");
        var jdbc = org.mockito.Mockito.mock(org.springframework.jdbc.core.JdbcTemplate.class);
        var quotes = new com.smartlect.biz.OrderQuoteService(jdbc,
                org.mockito.Mockito.mock(org.springframework.transaction.PlatformTransactionManager.class));
        ReflectionTestUtils.setField(service, "orderQuoteService", quotes);
        OrderItem quotedItem = new OrderItem();
        quotedItem.setProductId("p1");
        quotedItem.setPropertyValueIdHash("trusted");
        quotedItem.setBuyCount(1);
        quotedItem.setItemAmount(new BigDecimal("10.00"));
        var issued = quotes.issue("user-1", request, address(), List.of(quotedItem), new BigDecimal("10.00"));
        var fingerprint = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.eq("user-1"), org.mockito.ArgumentMatchers.anyString(), fingerprint.capture(),
                org.mockito.ArgumentMatchers.eq(1000L), org.mockito.ArgumentMatchers.any(java.sql.Timestamp.class),
                org.mockito.ArgumentMatchers.anyString());
        var quote = new com.smartlect.biz.OrderQuoteService.Quote((String) issued.get("quoteId"), "user-1",
                (String) issued.get("requestHash"), fingerprint.getValue(), 1000L,
                java.time.Instant.parse((String) issued.get("expiresAt")), null);
        ProductSnapshotBatchVO newerSnapshot = new ProductSnapshotBatchVO();
        when(userFeignSupport.getAddress("address-1", "user-1")).thenReturn(address());
        when(productFeignSupport.snapshotBatch(List.of("p1"))).thenReturn(newerSnapshot);
        when(productFeignSupport.toProductInfoMap(newerSnapshot)).thenReturn(Map.of("p1", product("p1", "Headphones")));
        when(productFeignSupport.toPropertyValueMap(newerSnapshot)).thenReturn(Map.of("p1v1", property("p1", "v1")));
        when(productFeignSupport.toSkuMapByPropertyValueIds(newerSnapshot)).thenReturn(Map.of("p1v1", sku("p1", "v1", "trusted", "11.00")));
        when(stockFeignSupport.getAvailable("p1", "trusted")).thenReturn(10);
        var error = org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.HttpBusinessException.class,
                () -> ReflectionTestUtils.invokeMethod(service, "createOrder", "user-1", request, quote, 1000L, null));
        assertEquals("RECONFIRM_REQUIRED", error.getMessage());
        verify(orderInfoMapper, never()).insertBatch(org.mockito.ArgumentMatchers.anyList());
        verify(orderItemMapper, never()).insertBatch(org.mockito.ArgumentMatchers.anyList());
        verify(stockFeignSupport, never()).changeStockBatch(
                org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.any());
        org.mockito.Mockito.verifyNoInteractions(payFeignSupport);
    }

    @Test
    void confirmedPriceMismatchUnlocksCouponBeforeAnyOrderPaymentOrStockMutation() {
        ProductItem line = item("p1", "v1", "ignored");
        PostOrderDTO request = request(List.of(line));
        request.setUserCouponId("uc1");
        ProductSnapshotBatchVO snapshot = new ProductSnapshotBatchVO();
        when(userFeignSupport.getAddress("address-1", "user-1")).thenReturn(address());
        when(productFeignSupport.snapshotBatch(List.of("p1"))).thenReturn(snapshot);
        when(productFeignSupport.toProductInfoMap(snapshot)).thenReturn(Map.of("p1", product("p1", "Headphones")));
        when(productFeignSupport.toPropertyValueMap(snapshot)).thenReturn(Map.of("p1v1", property("p1", "v1")));
        when(productFeignSupport.toSkuMapByPropertyValueIds(snapshot)).thenReturn(Map.of("p1v1", sku("p1", "v1", "trusted", "10.00")));
        when(stockFeignSupport.getAvailable("p1", "trusted")).thenReturn(10);
        com.smartlect.api.vo.CouponLockResultVO coupon = new com.smartlect.api.vo.CouponLockResultVO();
        coupon.setLocked(true);
        coupon.setCouponId("c1");
        coupon.setDiscountAmount(new BigDecimal("1.00"));
        when(couponFeignSupport.validateAndLock("user-1", "uc1", new BigDecimal("10.00"))).thenReturn(coupon);
        com.smartlect.biz.OrderQuoteService.Quote quote = new com.smartlect.biz.OrderQuoteService.Quote(
                "a".repeat(32), "user-1", "request", "offer", 800, java.time.Instant.now().plusSeconds(60), null);
        org.mockito.Mockito.doThrow(new com.smartlect.exception.HttpBusinessException(409, "RECONFIRM_REQUIRED"))
                .when(orderQuoteService).validate(org.mockito.ArgumentMatchers.eq(quote),
                        org.mockito.ArgumentMatchers.eq("user-1"), org.mockito.ArgumentMatchers.eq(request),
                        org.mockito.ArgumentMatchers.eq(800L), org.mockito.ArgumentMatchers.any(),
                        org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.eq(new BigDecimal("9.00")));
        org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.HttpBusinessException.class,
                () -> ReflectionTestUtils.invokeMethod(service, "createOrder", "user-1", request, quote, 800L, null));
        org.mockito.InOrder sequence = org.mockito.Mockito.inOrder(couponFeignSupport, stockFeignSupport, orderQuoteService);
        sequence.verify(couponFeignSupport).validateAndLock("user-1", "uc1", new BigDecimal("10.00"));
        sequence.verify(orderQuoteService).validate(org.mockito.ArgumentMatchers.eq(quote),
                org.mockito.ArgumentMatchers.eq("user-1"), org.mockito.ArgumentMatchers.eq(request),
                org.mockito.ArgumentMatchers.eq(800L), org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.eq(new BigDecimal("9.00")));
        verify(couponFeignSupport).changeUserCouponStatus("uc1", "user-1",
                com.smartlect.api.enums.UserCouponStatusEnum.CANT.getStatus(),
                com.smartlect.api.enums.UserCouponStatusEnum.NOUSE.getStatus(), null);
        verify(orderInfoMapper, never()).insertBatch(org.mockito.ArgumentMatchers.anyList());
        verify(orderItemMapper, never()).insertBatch(org.mockito.ArgumentMatchers.anyList());
        verify(orderCouponRelMapper, never()).insert(org.mockito.ArgumentMatchers.any());
        verify(stockFeignSupport, never()).changeStockBatch(
                org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.any());
        org.mockito.Mockito.verifyNoInteractions(payFeignSupport);
    }

    @Test
    void conditionalDeductFailureLeavesNoStockMutationAndUnlocksCoupon() {
        ProductItem line = item("p1", "v1", "ignored");
        PostOrderDTO request = request(List.of(line));
        ProductSnapshotBatchVO snapshot = new ProductSnapshotBatchVO();
        when(userFeignSupport.getAddress("address-1", "user-1")).thenReturn(address());
        when(productFeignSupport.snapshotBatch(List.of("p1"))).thenReturn(snapshot);
        when(productFeignSupport.toProductInfoMap(snapshot)).thenReturn(Map.of("p1", product("p1", "Headphones")));
        when(productFeignSupport.toPropertyValueMap(snapshot)).thenReturn(Map.of("p1v1", property("p1", "v1")));
        when(productFeignSupport.toSkuMapByPropertyValueIds(snapshot)).thenReturn(Map.of(
                "p1v1", sku("p1", "v1", "trusted", "10.00")));
        when(stockFeignSupport.getAvailable("p1", "trusted")).thenReturn(10);
        when(redisComponent.getLogisticsInfo()).thenReturn(sender());
        doThrow(new RuntimeException("stock_deduct_failed"))
                .when(stockFeignSupport).changeStockBatch(
                        org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.anyString());

        assertThrows(RuntimeException.class,
                () -> ReflectionTestUtils.invokeMethod(service, "createOrder", "user-1", request));

        // 库存一步化：扣减是条件更新本身，失败（库存不足）即上抛，无"先锁后扣"中间态，
        // 也不再有 deduct 之外的库存写需要回补。
        verify(stockFeignSupport).changeStockBatch(
                org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.anyString());
        verify(stockFeignSupport, org.mockito.Mockito.times(1))
                .changeStockBatch(org.mockito.ArgumentMatchers.anyList(), org.mockito.ArgumentMatchers.anyString());
        verify(stockFeignSupport, never()).restoreOrderStock(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyList());
    }

    @Test
    void payTimeoutMessageIsWrittenInsidePhase3Transaction() {
        // ADR-0018：超时关单消息必须与订单落库同事务写入 Outbox——旧实现在 Phase 4
        // 末尾才发送，扣库存/建支付意图失败会留下既无支付意图又无关单消息的永久孤儿订单。
        ProductItem line = item("p1", "v1", "ignored");
        PostOrderDTO request = request(List.of(line));
        ProductSnapshotBatchVO snapshot = new ProductSnapshotBatchVO();
        when(userFeignSupport.getAddress("address-1", "user-1")).thenReturn(address());
        when(productFeignSupport.snapshotBatch(List.of("p1"))).thenReturn(snapshot);
        when(productFeignSupport.toProductInfoMap(snapshot)).thenReturn(Map.of("p1", product("p1", "Headphones")));
        when(productFeignSupport.toPropertyValueMap(snapshot)).thenReturn(Map.of("p1v1", property("p1", "v1")));
        when(productFeignSupport.toSkuMapByPropertyValueIds(snapshot)).thenReturn(Map.of("p1v1", sku("p1", "v1", "trusted", "10.00")));
        when(stockFeignSupport.getAvailable("p1", "trusted")).thenReturn(10);
        when(redisComponent.getLogisticsInfo()).thenReturn(sender());

        // 捕获 Phase 3 事务回调：回调执行前不允许有任何关单消息写出（消息在事务块内）。
        org.mockito.Mockito.doAnswer(call -> {
            @SuppressWarnings("unchecked")
            java.util.function.Consumer<org.springframework.transaction.TransactionStatus> cb = call.getArgument(0);
            org.mockito.Mockito.verify(transactionalMqSender, org.mockito.Mockito.never()).sendAfterCommit(
                    org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                    org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.anyString(),
                    org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any());
            cb.accept(null);
            return null;
        }).when(transactionTemplate).executeWithoutResult(
                org.mockito.ArgumentMatchers.<java.util.function.Consumer<org.springframework.transaction.TransactionStatus>>any());

        ReflectionTestUtils.invokeMethod(service, "createOrder", "user-1", request);

        // 单商品单订单：恰好一条关单消息，topic/tag 与 pay:timeout 幂等键正确。
        var dtoCaptor = ArgumentCaptor.forClass(com.smartlect.api.dto.PayOrderMessageDTO.class);
        verify(transactionalMqSender).sendAfterCommit(
                org.mockito.ArgumentMatchers.eq(com.smartlect.mq.RocketMqTopics.TOPIC_DELAY),
                org.mockito.ArgumentMatchers.eq(com.smartlect.mq.RocketMqTopics.TAG_PAY_TIMEOUT_CLOSE),
                dtoCaptor.capture(),
                org.mockito.ArgumentMatchers.startsWith("pay:timeout:"),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any());
        // 订单确实已随同一事务块写入。
        verify(orderInfoMapper).insertBatch(org.mockito.ArgumentMatchers.anyList());
    }

    private static PostOrderDTO request(List<ProductItem> items) {
        PostOrderDTO request = new PostOrderDTO();
        request.setPayMethod("mock");
        request.setAddressId("address-1");
        request.setOrderFrom(OrderFromTypeEnum.PRODUCT.getType());
        request.setOrderList(items);
        return request;
    }

    private static ProductItem item(String productId, String propertyValueIds, String forgedHash) {
        ProductItem item = new ProductItem();
        item.setProductId(productId);
        item.setPropertyValueIds(propertyValueIds);
        item.setPropertyValueIdHash(forgedHash);
        item.setBuyCount(1);
        return item;
    }

    private static UserAddressVO address() {
        UserAddressVO address = new UserAddressVO();
        address.setAddress("Shanghai");
        address.setAddressee("Demo User");
        address.setPhone("13800000000");
        return address;
    }

    private static LogisticsSendDTO sender() {
        LogisticsSendDTO sender = new LogisticsSendDTO();
        sender.setSenderName("AI Shop");
        sender.setSenderPhone("021-12345678");
        sender.setSenderAddress("Warehouse");
        return sender;
    }

    private static ProductInfoSnapshotVO product(String productId, String name) {
        ProductInfoSnapshotVO product = new ProductInfoSnapshotVO();
        product.setProductId(productId);
        product.setProductName(name);
        product.setStatus(ProductStatusEnum.ON_SALE.getStatus());
        return product;
    }

    private static ProductPropertyValueSnapshotVO property(String productId, String valueId) {
        ProductPropertyValueSnapshotVO property = new ProductPropertyValueSnapshotVO();
        property.setProductId(productId);
        property.setPropertyValueId(valueId);
        property.setPropertyName("Style");
        property.setPropertyValue(valueId);
        return property;
    }

    private static ProductSkuSnapshotVO sku(
            String productId, String propertyValueIds, String hash, String price) {
        ProductSkuSnapshotVO sku = new ProductSkuSnapshotVO();
        sku.setProductId(productId);
        sku.setPropertyValueIds(propertyValueIds);
        sku.setPropertyValueIdHash(hash);
        sku.setPrice(new BigDecimal(price));
        return sku;
    }

    private static Set<String> hashes(List<ProductItem> items) {
        return items.stream().map(ProductItem::getPropertyValueIdHash).collect(Collectors.toSet());
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private static <T> ArgumentCaptor<List<T>> listCaptor() {
        return (ArgumentCaptor) ArgumentCaptor.forClass(List.class);
    }
}
