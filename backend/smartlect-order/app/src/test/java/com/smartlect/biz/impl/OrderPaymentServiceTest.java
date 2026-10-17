package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.OrderFromTypeEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批次二支付回调短事务化（ADR-0002）的结构性锚定：
 * assertSettled（远程读）在短事务之前，券核销与 markSuccess（远程写）在短事务之后——
 * 远程调用不再占用本地数据库连接。
 */
@ExtendWith(MockitoExtension.class)
class OrderPaymentServiceTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderItemMapper<com.smartlect.entity.po.OrderItem, com.smartlect.entity.query.OrderItemQuery> orderItemMapper;
    @Mock
    private OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;
    @Mock
    private OrderCouponRelMapper<com.smartlect.entity.po.OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    @Mock
    private TransactionTemplate transactionTemplate;
    @Mock
    private OrderStateMachine orderStateMachine;
    @Mock
    private RedisComponent redisComponent;
    @Mock
    private PayOrderRedisComponent payOrderRedisComponent;
    @Mock
    private PayRpcSupport payRpcSupport;
    @Mock
    private CouponRpcSupport couponRpcSupport;
    @Mock
    private CouponRushOrderService couponRushOrderService;
    @Mock
    private TransactionalMqSender transactionalMqSender;

    private OrderPaymentService service;

    @BeforeEach
    void setUp() {
        service = new OrderPaymentService(orderInfoMapper, orderItemMapper,
                orderLogisticsInfoMapper, orderCouponRelMapper, transactionTemplate, orderStateMachine,
                redisComponent, payOrderRedisComponent, payRpcSupport, couponRpcSupport,
                couponRushOrderService, transactionalMqSender);
        lenient().doAnswer(invocation -> {
            invocation.getArgument(1, Runnable.class).run();
            return null;
        }).when(payOrderRedisComponent).runWithPayOrderLifecycleLock(anyString(), any(Runnable.class));
    }

    @Test
    void remoteCallsStayOutsideTheShortLocalTransaction() {
        OrderInfo order = new OrderInfo();
        order.setOrderId("order-1");
        order.setUserId("user-1");
        order.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
        order.setAmount(new java.math.BigDecimal("10.00"));
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(order));
        OrderLogisticsInfo logistics = new OrderLogisticsInfo();
        logistics.setReceiverName("收件人");
        when(orderLogisticsInfoMapper.selectByOrderId("order-1")).thenReturn(logistics);
        when(orderStateMachine.transition(eq("order-1"), eq(OrderStatusEnum.WAIT_PAYMENT),
                eq(OrderStateEvent.PAY_SUCCESS), any(OrderInfo.class))).thenReturn(1);
        when(orderCouponRelMapper.selectList(any())).thenReturn(List.of());
        // 短事务透传执行
        when(transactionTemplate.execute(any())).thenAnswer(call -> {
            TransactionCallback<?> callback = call.getArgument(0);
            return callback.doInTransaction(null);
        });

        service.paySuccess(new PayOrderNotifyDTO("pay-1", "channel-1"));

        // 顺序锚定：assertSettled（事务外远程读）→ 短事务内状态机翻单 → markSuccess（事务外远程写）。
        // 本用例订单无券关系，券核销路径不产生 coupon 调用。
        var sequence = inOrder(payRpcSupport, orderStateMachine);
        sequence.verify(payRpcSupport).assertSettled("pay-1");
        sequence.verify(orderStateMachine).transition(eq("order-1"), eq(OrderStatusEnum.WAIT_PAYMENT),
                eq(OrderStateEvent.PAY_SUCCESS), any(OrderInfo.class));
        sequence.verify(payRpcSupport).markSuccess(eq("pay-1"), eq("channel-1"));
    }

    /**
     * 回归：首次回调在事务外核销券失败 → 订单已 PAID；重投命中"已支付"早退分支时，
     * 必须补一次幂等核销，否则券永久停在 CANT（退款还券也会跳过 CANT）。
     */
    @Test
    void couponRedemptionIsRetriedWhenPaymentEventIsRedeliveredAfterRemoteFailure() {
        OrderInfo waitPay = order("order-1", OrderStatusEnum.WAIT_PAYMENT);
        OrderInfo paid = order("order-1", OrderStatusEnum.PAID);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(waitPay), List.of(paid));
        OrderLogisticsInfo logistics = new OrderLogisticsInfo();
        logistics.setReceiverName("收件人");
        when(orderLogisticsInfoMapper.selectByOrderId("order-1")).thenReturn(logistics);
        when(orderStateMachine.transition(eq("order-1"), eq(OrderStatusEnum.WAIT_PAYMENT),
                eq(OrderStateEvent.PAY_SUCCESS), any(OrderInfo.class))).thenReturn(1);
        OrderCouponRel rel = new OrderCouponRel();
        rel.setOrderId("order-1");
        rel.setUserCouponId("uc-1");
        when(orderCouponRelMapper.selectList(any())).thenReturn(List.of(rel));
        when(transactionTemplate.execute(any())).thenAnswer(call -> {
            TransactionCallback<?> callback = call.getArgument(0);
            return callback.doInTransaction(null);
        });
        doThrow(new com.smartlect.exception.BusinessException("券服务不可用"))
                .doNothing()
                .when(couponRpcSupport).changeUserCouponStatus(eq("uc-1"), eq("user-1"),
                        eq(UserCouponStatusEnum.CANT.getStatus()), eq(UserCouponStatusEnum.USED.getStatus()), any());

        assertThrows(com.smartlect.exception.BusinessException.class,
                () -> service.paySuccess(new PayOrderNotifyDTO("pay-1", "channel-1")));

        // 重投：订单已 PAID → 早退分支补核销
        service.paySuccess(new PayOrderNotifyDTO("pay-1", "channel-1"));

        verify(couponRpcSupport, times(2)).changeUserCouponStatus(eq("uc-1"), eq("user-1"),
                eq(UserCouponStatusEnum.CANT.getStatus()), eq(UserCouponStatusEnum.USED.getStatus()), any());
    }

    /** 全额退款后券已还成 NOUSE（退款还券 USED→NOUSE），重投不得再核销，否则会永久重抛。 */
    @Test
    void refundedOrderDoesNotRedeemCouponAgain() {
        OrderInfo refunded = order("order-1", OrderStatusEnum.REFUNDED);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(refunded));

        service.paySuccess(new PayOrderNotifyDTO("pay-1", "channel-1"));

        verify(couponRpcSupport, never()).changeUserCouponStatus(any(), any(), any(), any(), any());
    }

    /** 秒杀单同形缺陷：已完成但激活失败，重投必须补激活（CANT→NOUSE）。 */
    @Test
    void couponRushActivationIsRetriedWhenPaymentEventIsRedelivered() {
        OrderInfo completed = order("order-1", OrderStatusEnum.COMPLETED);
        completed.setPayScene(String.valueOf(OrderFromTypeEnum.COUPON.getType()));
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(completed));
        OrderCouponRel rel = new OrderCouponRel();
        rel.setOrderId("order-1");
        rel.setUserCouponId("uc-1");
        when(orderCouponRelMapper.selectList(any())).thenReturn(List.of(rel));

        service.paySuccess(new PayOrderNotifyDTO("pay-1", "channel-1"));

        verify(couponRushOrderService).activateUserCoupon("user-1", "uc-1");
        verify(couponRpcSupport, never()).changeUserCouponStatus(any(), any(), any(), any(), any());
    }

    private static OrderInfo order(String orderId, OrderStatusEnum status) {
        OrderInfo order = new OrderInfo();
        order.setOrderId(orderId);
        order.setUserId("user-1");
        order.setOrderStatus(status.getStatus());
        order.setAmount(new java.math.BigDecimal("10.00"));
        return order;
    }
}
