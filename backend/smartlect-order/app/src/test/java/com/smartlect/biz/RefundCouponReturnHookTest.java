package com.smartlect.biz;

import com.smartlect.api.dto.RefundCouponReturnDTO;
import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.RefundRequestMapper;
import com.smartlect.state.OrderStateMachine;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anySet;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 退款全额还券钩子（ADR-0020）：仅整单全额退（无剩余正常明细）时发还券事件，
 * 事件与 Saga 收尾同事务（sendAfterCommit 在调用方事务内落 Outbox）。
 */
@ExtendWith(MockitoExtension.class)
class RefundCouponReturnHookTest {

    @Mock
    private RefundRequestMapper refundRequestMapper;
    @Mock
    private OrderInfoMapper<OrderInfo, ?> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, ?> orderItemMapper;
    @Mock
    private TransactionalMqSender transactionalMqSender;
    @Mock
    private OrderStateMachine orderStateMachine;
    @Mock
    private OrderCouponRelMapper<OrderCouponRel, com.smartlect.entity.query.OrderCouponRelQuery> orderCouponRelMapper;

    private RefundSagaTransactionService service;

    @BeforeEach
    void setUp() {
        service = new RefundSagaTransactionService();
        ReflectionTestUtils.setField(service, "refundRequestMapper", refundRequestMapper);
        ReflectionTestUtils.setField(service, "orderInfoMapper", orderInfoMapper);
        ReflectionTestUtils.setField(service, "orderItemMapper", orderItemMapper);
        ReflectionTestUtils.setField(service, "transactionalMqSender", transactionalMqSender);
        ReflectionTestUtils.setField(service, "orderStateMachine", orderStateMachine);
        ReflectionTestUtils.setField(service, "orderCouponRelMapper", orderCouponRelMapper);
    }

    @Test
    void fullRefundEmitsCouponReturnEventInsideSagaTransaction() {
        when(orderStateMachine.transition(anyString(), anySet(), any(), any())).thenReturn(1);
        stubItemOrderAndRel(0);

        ReflectionTestUtils.invokeMethod(service, "finalizeOrderRefund", refundRequest());

        verify(transactionalMqSender).sendAfterCommit(
                eq(com.smartlect.mq.RocketMqTopics.TOPIC_REFUND),
                eq(com.smartlect.mq.RocketMqTopics.TAG_REFUND_COUPON_RETURN),
                any(RefundCouponReturnDTO.class),
                eq("refund-return-coupon:order-1"),
                any(),
                isNull());
    }

    @Test
    void siblingOrdersUnderSamePayOrderUseDistinctCouponReturnKeys() {
        // 一次结算拆多张订单、共用一张券：两单各自全额退款时，事件键必须不同，
        // 否则第二单会命中 Outbox"同键不同载荷"断言并抛错 → 退款卡在 PAYMENT_CONFIRMED
        //（2026-10-16 审计 H2）。这里断言键取自 orderId 而不是 payOrderId。
        when(orderStateMachine.transition(anyString(), anySet(), any(), any())).thenReturn(1);
        stubItemOrderAndRel(0);

        ReflectionTestUtils.invokeMethod(service, "finalizeOrderRefund", refundRequest());

        var captor = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(transactionalMqSender).sendAfterCommit(
                anyString(), anyString(), any(RefundCouponReturnDTO.class),
                captor.capture(), any(), isNull());
        assertTrue(captor.getValue().startsWith("refund-return-coupon:order-"),
                "事件键必须按订单维度：" + captor.getValue());
        assertFalse(captor.getValue().contains("pay-1"),
                "键里不应再出现支付单号（它是聚合级、兄弟订单会撞）");
    }

    @Test
    void partialRefundDoesNotReturnCoupon() {
        when(orderStateMachine.transition(anyString(), anySet(), any(), any())).thenReturn(1);
        stubItemOrderAndRel(2);

        ReflectionTestUtils.invokeMethod(service, "finalizeOrderRefund", refundRequest());

        verify(transactionalMqSender, never()).sendAfterCommit(
                anyString(), anyString(), any(), anyString(), any(), any());
    }

    private void stubItemOrderAndRel(int normalCount) {
        OrderItem item = new OrderItem();
        item.setOrderItemId("item-1");
        item.setOrderId("order-1");
        item.setPaidAmount(new BigDecimal("10.00"));
        item.setRefundedAmount(new BigDecimal("10.00"));
        item.setOrderItemStatus(OrderItemStatusEnum.REFUND.getStatus());
        when(orderItemMapper.selectByOrderItemIdForUpdate("item-1")).thenReturn(item);
        OrderInfo order = new OrderInfo();
        order.setOrderId("order-1");
        order.setPayOrderId("pay-1");
        order.setOrderStatus(OrderStatusEnum.PAID.getStatus());
        when(orderInfoMapper.selectByOrderIdForUpdate("order-1")).thenReturn(order);
        when(orderItemMapper.countNormalByOrderId("order-1")).thenReturn(normalCount);
        OrderCouponRel rel = new OrderCouponRel();
        rel.setOrderId("order-1");
        rel.setUserCouponId("uc-1");
        rel.setCouponId("c1");
        lenient().when(orderCouponRelMapper.selectList(any())).thenReturn(List.of(rel));
    }

    private static RefundRequest refundRequest() {
        RefundRequest request = new RefundRequest();
        request.setOrderItemId("item-1");
        request.setOrderId("order-1");
        request.setRefundAmount(new BigDecimal("10.00"));
        return request;
    }
}
