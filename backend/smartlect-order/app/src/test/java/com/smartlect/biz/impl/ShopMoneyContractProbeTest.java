package com.smartlect.biz.impl;

import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.biz.RefundSagaTransactionService;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.RefundRequestMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import java.util.ArrayList;
import com.smartlect.exception.BusinessException;
import com.smartlect.biz.OrderInternalService;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Smartlect regression probes for equal-weight payments and discounted cash refunds. */
@SuppressWarnings("unchecked")
class ShopMoneyContractProbeTest {
    @Test
    void equalPriceSkuLinesReceiveEqualPaidAmounts() {
        // recordPaymentOutcomes 已随批次二拆分移入 OrderPaymentService；该方法只依赖 orderItemMapper（构造器第 2 参）
        OrderItemMapper<OrderItem, OrderItemQuery> items = mock(OrderItemMapper.class);
        var service = new OrderPaymentService(null, items, null, null, null,
                null, null, null, null, null, null, null);
        when(items.selectList(any(OrderItemQuery.class))).thenReturn(List.of(item("1"), item("2"), item("3")));
        when(items.recordPaidAmount(anyString(), any())).thenReturn(1);

        ReflectionTestUtils.invokeMethod(service, "recordPaymentOutcomes", List.of(order("300.00")), "pay-1");

        var paid = ArgumentCaptor.forClass(java.math.BigDecimal.class);
        verify(items, times(3)).recordPaidAmount(anyString(), paid.capture());
        assertEquals(List.of(new BigDecimal("100.00"), new BigDecimal("100.00"), new BigDecimal("100.00")), paid.getAllValues());
    }

    @Test
    void discountedSingleLineRefundCannotExceedPaidAmount() {
        var service = new RefundSagaTransactionService();
        var requests = mock(RefundRequestMapper.class);
        OrderItemMapper<OrderItem, ?> items = mock(OrderItemMapper.class);
        OrderInfoMapper<OrderInfo, ?> orders = mock(OrderInfoMapper.class);
        ReflectionTestUtils.setField(service, "refundRequestMapper", requests);
        ReflectionTestUtils.setField(service, "orderItemMapper", items);
        ReflectionTestUtils.setField(service, "orderInfoMapper", orders);
        var stored = new AtomicReference<RefundRequest>();
        when(requests.selectByOrderItemId("item-1")).thenAnswer(call -> stored.get());
        when(requests.insertIgnore(any(RefundRequest.class))).thenAnswer(call -> {
            stored.set(call.getArgument(0));
            return 1;
        });
        OrderItem paidLine = item("1");
        paidLine.setPaidAmount(new BigDecimal("90.00"));
        when(items.selectByOrderItemIdForUpdate("item-1")).thenReturn(paidLine);
        when(orders.selectByOrderIdForUpdate("order-1")).thenReturn(order("90.00"));

        RefundRequest result = service.createOrLoad("item-1", "user-1");

        assertEquals(new BigDecimal("90.00"), result.getRefundAmount());
        assertSame(result, service.createOrLoad("item-1", "user-1"));
        verify(requests, times(1)).insertIgnore(any(RefundRequest.class));
    }

    @Test
    void manyTinyLinesAndZeroPriceLinesStayBoundedAndConserveEveryCent() {
        OrderItemMapper<OrderItem, OrderItemQuery> items = mock(OrderItemMapper.class);
        var service = new OrderPaymentService(null, items, null, null, null,
                null, null, null, null, null, null, null);
        List<OrderItem> lines = new ArrayList<>();
        for (int index = 0; index < 100; index++) {
            OrderItem line = item(String.format("%03d", index));
            line.setItemAmount(new BigDecimal("0.01"));
            lines.add(line);
        }
        OrderItem free = item("free");
        free.setItemAmount(new BigDecimal("0.00"));
        lines.add(free);
        when(items.selectList(any(OrderItemQuery.class))).thenReturn(lines);
        when(items.recordPaidAmount(anyString(), any())).thenReturn(1);

        ReflectionTestUtils.invokeMethod(service, "recordPaymentOutcomes", List.of(order("0.49")), "pay-1");

        assertEquals(new BigDecimal("0.49"), lines.stream().map(OrderItem::getPaidAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add));
        assertEquals(new BigDecimal("0.00"), free.getPaidAmount());
        assertTrue(lines.stream().allMatch(line -> line.getPaidAmount().signum() >= 0
                && line.getPaidAmount().compareTo(line.getItemAmount()) <= 0));
        verify(items, times(101)).recordPaidAmount(anyString(), any());
    }

    @Test
    void missingPaidAllocationCannotCreateCashRefund() {
        var service = new RefundSagaTransactionService();
        var requests = mock(RefundRequestMapper.class);
        OrderItemMapper<OrderItem, ?> items = mock(OrderItemMapper.class);
        OrderInfoMapper<OrderInfo, ?> orders = mock(OrderInfoMapper.class);
        ReflectionTestUtils.setField(service, "refundRequestMapper", requests);
        ReflectionTestUtils.setField(service, "orderItemMapper", items);
        ReflectionTestUtils.setField(service, "orderInfoMapper", orders);
        when(items.selectByOrderItemIdForUpdate("item-1")).thenReturn(item("1"));
        when(orders.selectByOrderIdForUpdate("order-1")).thenReturn(order("90.00"));
        assertThrows(BusinessException.class, () -> service.createOrLoad("item-1", "user-1"));
        verify(requests, never()).insertIgnore(any());
    }

    @Test
    void refundedLineStatisticsUsePersistedCashRatherThanOriginalPrice() {
        OrderItem line = item("1");
        line.setPaidAmount(new BigDecimal("90.00"));
        line.setRefundedAmount(new BigDecimal("90.00"));
        line.setOrderItemStatus(OrderItemStatusEnum.REFUND.getStatus());
        OrderInfo order = order("90.00");
        order.setOrderItemList(List.of(line));
        var stats = new OrderInternalService();
        assertEquals(new BigDecimal("90.00"), ReflectionTestUtils.invokeMethod(stats, "sumNonNormalItemAmount", order));
        assertEquals(new BigDecimal("0.00"), ReflectionTestUtils.invokeMethod(stats, "calcEffectiveSaleAmount", order));
    }

    private static OrderInfo order(String paidAmount) {
        var order = new OrderInfo();
        order.setOrderId("order-1");
        order.setPayOrderId("pay-1");
        order.setUserId("user-1");
        order.setOrderStatus(OrderStatusEnum.PAID.getStatus());
        order.setPayChannel("mock");
        order.setAmount(new BigDecimal(paidAmount));
        return order;
    }

    private static OrderItem item(String suffix) {
        var item = new OrderItem();
        item.setOrderItemId("item-" + suffix);
        item.setOrderId("order-1");
        item.setProductId("product-1");
        item.setPropertyValueIdHash("sku-" + suffix);
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("100.00"));
        item.setOrderItemStatus(OrderItemStatusEnum.NORMAL.getStatus());
        return item;
    }
}
