package com.smartlect.state;

import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderStatusLog;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderStatusLogMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 订单状态机：转移表规则、CAS 查询形状与非法流转拒绝。
 */
@ExtendWith(MockitoExtension.class)
class OrderStateMachineTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderStatusLogMapper orderStatusLogMapper;

    @InjectMocks
    private OrderStateMachine stateMachine;

    @Test
    void transitionTableEdges() {
        assertTrue(stateMachine.canTransition(0, OrderStateEvent.PAY_SUCCESS));
        assertEquals(OrderStatusEnum.PAID, stateMachine.target(0, OrderStateEvent.PAY_SUCCESS));
        assertEquals(OrderStatusEnum.COMPLETED, stateMachine.target(0, OrderStateEvent.COUPON_RUSH_PAY_SUCCESS));
        assertEquals(OrderStatusEnum.CANCELLED, stateMachine.target(0, OrderStateEvent.USER_CANCEL));
        assertEquals(OrderStatusEnum.CLOSED, stateMachine.target(0, OrderStateEvent.SYSTEM_CANCEL));
        assertEquals(OrderStatusEnum.CLOSED, stateMachine.target(0, OrderStateEvent.PAYMENT_TIMEOUT));
        assertEquals(OrderStatusEnum.SHIPPED, stateMachine.target(1, OrderStateEvent.SHIP));
        assertEquals(OrderStatusEnum.PARTIALLY_REFUNDED, stateMachine.target(1, OrderStateEvent.PARTIAL_REFUND));
        assertEquals(OrderStatusEnum.PARTIALLY_REFUNDED, stateMachine.target(7, OrderStateEvent.PARTIAL_REFUND));
        assertEquals(OrderStatusEnum.REFUNDED, stateMachine.target(2, OrderStateEvent.FULL_REFUND));
        assertEquals(OrderStatusEnum.COMPLETED, stateMachine.target(2, OrderStateEvent.CONFIRM_RECEIPT));
        assertEquals(OrderStatusEnum.COMPLETED, stateMachine.target(7, OrderStateEvent.CONFIRM_RECEIPT));
        assertEquals(OrderStatusEnum.DELETE, stateMachine.target(3, OrderStateEvent.DELETE));
        assertEquals(OrderStatusEnum.DELETE, stateMachine.target(6, OrderStateEvent.DELETE));
    }

    @Test
    void illegalTransitionThrowsAtTargetResolution() {
        assertThrows(BusinessException.class, () -> stateMachine.target(0, OrderStateEvent.SHIP));
        assertThrows(BusinessException.class, () -> stateMachine.target(1, OrderStateEvent.PAY_SUCCESS));
        assertThrows(BusinessException.class, () -> stateMachine.target(3, OrderStateEvent.USER_CANCEL));
        assertThrows(BusinessException.class, () -> stateMachine.target(0, OrderStateEvent.DELETE));
        assertFalse(stateMachine.canTransition(null, OrderStateEvent.PAY_SUCCESS));
    }

    @Test
    void casUpdateCarriesOldStatusConditionAndTargetStatus() {
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(1);
        int rows = stateMachine.transition("o-1", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAY_SUCCESS);
        assertEquals(1, rows);
        ArgumentCaptor<OrderInfo> update = ArgumentCaptor.forClass(OrderInfo.class);
        ArgumentCaptor<OrderInfoQuery> query = ArgumentCaptor.forClass(OrderInfoQuery.class);
        verify(orderInfoMapper).updateByParam(update.capture(), query.capture());
        assertEquals(OrderStatusEnum.PAID.getStatus(), update.getValue().getOrderStatus());
        assertEquals("o-1", query.getValue().getOrderId());
        assertEquals(OrderStatusEnum.WAIT_PAYMENT.getStatus(), query.getValue().getOrderStatus());
    }

    @Test
    void multiExpectedStatesUseInCondition() {
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(1);
        stateMachine.transition("o-1",
                Set.of(OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED),
                OrderStateEvent.CONFIRM_RECEIPT);
        ArgumentCaptor<OrderInfo> update = ArgumentCaptor.forClass(OrderInfo.class);
        ArgumentCaptor<OrderInfoQuery> query = ArgumentCaptor.forClass(OrderInfoQuery.class);
        verify(orderInfoMapper).updateByParam(update.capture(), query.capture());
        assertEquals(2, query.getValue().getOrderStatusList().length);
        assertTrue(java.util.Arrays.asList(query.getValue().getOrderStatusList())
                .containsAll(java.util.Arrays.asList(
                        OrderStatusEnum.SHIPPED.getStatus(),
                        OrderStatusEnum.PARTIALLY_REFUNDED.getStatus())));
        assertEquals(OrderStatusEnum.COMPLETED.getStatus(), update.getValue().getOrderStatus());
    }

    @Test
    void patchKeepsExtraColumnsAndMachineOwnsStatus() {
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(1);
        OrderInfo patch = new OrderInfo();
        patch.setChannelOrderId("ch-9");
        stateMachine.transition("o-1", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAY_SUCCESS, patch);
        ArgumentCaptor<OrderInfo> update = ArgumentCaptor.forClass(OrderInfo.class);
        verify(orderInfoMapper).updateByParam(update.capture(), any());
        assertEquals("ch-9", update.getValue().getChannelOrderId());
        assertEquals(OrderStatusEnum.PAID.getStatus(), update.getValue().getOrderStatus());
    }

    @Test
    void idempotentReentryComparesBySelectInsteadOfUpdate() {
        OrderInfo current = new OrderInfo();
        current.setOrderStatus(OrderStatusEnum.PARTIALLY_REFUNDED.getStatus());
        when(orderInfoMapper.selectByOrderId("o-1")).thenReturn(current);
        // 前置=目标且无 patch：幂等读比对，不再发 UPDATE
        assertEquals(1, stateMachine.transition("o-1", OrderStatusEnum.PARTIALLY_REFUNDED,
                OrderStateEvent.PARTIAL_REFUND));
        verify(orderInfoMapper, never()).updateByParam(any(), any());
        current.setOrderStatus(OrderStatusEnum.PAID.getStatus());
        assertEquals(0, stateMachine.transition("o-1", OrderStatusEnum.PARTIALLY_REFUNDED,
                OrderStateEvent.PARTIAL_REFUND));
    }

    @Test
    void transitionPayOrderFiltersByPayOrderIdAndStatus() {
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(2);
        assertEquals(2, stateMachine.transitionPayOrder("po-1", OrderStatusEnum.WAIT_PAYMENT,
                OrderStateEvent.USER_CANCEL));
        ArgumentCaptor<OrderInfoQuery> query = ArgumentCaptor.forClass(OrderInfoQuery.class);
        verify(orderInfoMapper).updateByParam(any(), query.capture());
        assertEquals("po-1", query.getValue().getPayOrderId());
        assertEquals(OrderStatusEnum.WAIT_PAYMENT.getStatus(), query.getValue().getOrderStatus());
    }

    @Test
    void partialPayOrderTransitionRollsBackInsteadOfLoggingPhantomRows() {
        OrderInfo first = new OrderInfo();
        first.setOrderId("o-1");
        OrderInfo second = new OrderInfo();
        second.setOrderId("o-2");
        when(orderInfoMapper.selectList(any())).thenReturn(List.of(first, second));
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(1);

        assertThrows(BusinessException.class, () -> stateMachine.transitionPayOrder(
                "po-1", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.USER_CANCEL));
        verify(orderStatusLogMapper, never()).insert(any());
    }

    @Test
    void divergentTargetsAcrossExpectedStatesRejected() {
        // WAIT_PAYMENT--DELETE--> 无边；集合内非法组合在解析期抛出
        assertThrows(BusinessException.class, () -> stateMachine.transition("o-1",
                Set.of(OrderStatusEnum.PAID, OrderStatusEnum.WAIT_PAYMENT), OrderStateEvent.SHIP));
    }

    @Test
    void nullUpdateResultCountsAsZeroRows() {
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(null);
        assertEquals(0, stateMachine.transition("o-1", OrderStatusEnum.WAIT_PAYMENT,
                OrderStateEvent.PAY_SUCCESS));
    }

    @Test
    void successfulCasWritesStatusLogWithObservedFromState() {
        OrderInfo current = new OrderInfo();
        current.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
        current.setPayOrderId("po-1");
        when(orderInfoMapper.selectByOrderId("o-1")).thenReturn(current);
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(1);

        stateMachine.transition("o-1", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAY_SUCCESS);

        ArgumentCaptor<OrderStatusLog> log = ArgumentCaptor.forClass(OrderStatusLog.class);
        verify(orderStatusLogMapper).insert(log.capture());
        assertEquals("o-1", log.getValue().getOrderId());
        assertEquals("po-1", log.getValue().getPayOrderId());
        assertEquals(OrderStatusEnum.WAIT_PAYMENT.getStatus(), log.getValue().getFromStatus());
        assertEquals(OrderStatusEnum.PAID.getStatus(), log.getValue().getToStatus());
        assertEquals(OrderStateEvent.PAY_SUCCESS.name(), log.getValue().getEvent());
        assertEquals("SYSTEM", log.getValue().getOperatorType());
    }

    @Test
    void failedCasAndIdempotentReentryWriteNoStatusLog() {
        when(orderInfoMapper.selectByOrderId("o-1")).thenReturn(new OrderInfo());
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(0);
        assertEquals(0, stateMachine.transition("o-1", OrderStatusEnum.WAIT_PAYMENT,
                OrderStateEvent.PAY_SUCCESS));
        verify(orderStatusLogMapper, never()).insert(any());

        OrderInfo alreadyPartial = new OrderInfo();
        alreadyPartial.setOrderStatus(OrderStatusEnum.PARTIALLY_REFUNDED.getStatus());
        when(orderInfoMapper.selectByOrderId("o-1")).thenReturn(alreadyPartial);
        assertEquals(1, stateMachine.transition("o-1", OrderStatusEnum.PARTIALLY_REFUNDED,
                OrderStateEvent.PARTIAL_REFUND));
        verify(orderStatusLogMapper, never()).insert(any());
    }

    @Test
    void payOrderTransitionWritesOneLogPerAffectedOrder() {
        OrderInfo first = new OrderInfo();
        first.setOrderId("o-1");
        first.setPayOrderId("po-1");
        OrderInfo second = new OrderInfo();
        second.setOrderId("o-2");
        second.setPayOrderId("po-1");
        when(orderInfoMapper.selectList(any())).thenReturn(List.of(first, second));
        when(orderInfoMapper.updateByParam(any(), any())).thenReturn(2);

        stateMachine.transitionPayOrder("po-1", OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.USER_CANCEL);

        ArgumentCaptor<OrderStatusLog> logs = ArgumentCaptor.forClass(OrderStatusLog.class);
        verify(orderStatusLogMapper, org.mockito.Mockito.times(2)).insert(logs.capture());
        assertEquals(List.of("o-1", "o-2"), logs.getAllValues().stream()
                .map(OrderStatusLog::getOrderId).toList());
        assertEquals(OrderStatusEnum.CANCELLED.getStatus(), logs.getAllValues().get(0).getToStatus());
    }
}
