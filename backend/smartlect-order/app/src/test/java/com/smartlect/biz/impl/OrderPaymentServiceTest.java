package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.support.CouponFeignSupport;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.TransactionalMqSender;
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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批次二支付回调短事务化（ADR-0019）的结构性锚定：
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
    private PayFeignSupport payFeignSupport;
    @Mock
    private CouponFeignSupport couponFeignSupport;
    @Mock
    private CouponRushOrderService couponRushOrderService;
    @Mock
    private TransactionalMqSender transactionalMqSender;

    private OrderPaymentService service;

    @BeforeEach
    void setUp() {
        service = new OrderPaymentService(orderInfoMapper, orderItemMapper,
                orderLogisticsInfoMapper, orderCouponRelMapper, transactionTemplate, orderStateMachine,
                redisComponent, payOrderRedisComponent, payFeignSupport, couponFeignSupport,
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
        var sequence = inOrder(payFeignSupport, orderStateMachine);
        sequence.verify(payFeignSupport).assertSettled("pay-1");
        sequence.verify(orderStateMachine).transition(eq("order-1"), eq(OrderStatusEnum.WAIT_PAYMENT),
                eq(OrderStateEvent.PAY_SUCCESS), any(OrderInfo.class));
        sequence.verify(payFeignSupport).markSuccess(eq("pay-1"), eq("channel-1"));
    }
}
