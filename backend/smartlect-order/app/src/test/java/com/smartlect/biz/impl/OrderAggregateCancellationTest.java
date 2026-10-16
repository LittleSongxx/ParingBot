package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RemoteCompensateRecorder;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderAggregateCancellationTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    @Mock
    private OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    @Mock
    private PayOrderRedisComponent payOrderRedisComponent;
    @Mock
    private StockRpcSupport stockRpcSupport;
    @Mock
    private PayRpcSupport payRpcSupport;
    @Mock
    private CouponRpcSupport couponRpcSupport;
    @Mock
    private RemoteCompensateRecorder remoteCompensateRecorder;
    @Mock
    private org.springframework.transaction.support.TransactionTemplate transactionTemplate;
    private OrderCancellationService service;

    @org.junit.jupiter.api.BeforeEach
    void wireService() {
        // 真实状态机 + mock mapper（CAS 语义必须是真的）；短事务模板透传执行回调
        com.smartlect.state.OrderStateMachine machine = new com.smartlect.state.OrderStateMachine();
        ReflectionTestUtils.setField(machine, "orderInfoMapper", orderInfoMapper);
        org.mockito.Mockito.lenient().when(transactionTemplate.execute(
                        org.mockito.ArgumentMatchers.<org.springframework.transaction.support.TransactionCallback<Object>>any()))
                .thenAnswer(call -> call.<org.springframework.transaction.support.TransactionCallback<Object>>getArgument(0)
                        .doInTransaction(null));
        this.service = new OrderCancellationService(orderInfoMapper, orderItemMapper, orderCouponRelMapper,
                transactionTemplate, machine, payOrderRedisComponent, payRpcSupport, stockRpcSupport,
                couponRpcSupport, remoteCompensateRecorder);
    }

    @BeforeEach
    void executeLifecycleLockBody() {
        lenient().doAnswer(invocation -> {
            invocation.getArgument(1, Runnable.class).run();
            return null;
        }).when(payOrderRedisComponent).runWithPayOrderLifecycleLock(anyString(), any(Runnable.class));
    }

    @Test
    void cancellingOneChildCancelsAndRestoresTheWholePaymentAggregate() {
        OrderInfo first = order("order-1", "pay-1", OrderStatusEnum.WAIT_PAYMENT);
        OrderInfo second = order("order-2", "pay-1", OrderStatusEnum.WAIT_PAYMENT);
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(first);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(first, second));
        when(orderInfoMapper.updateByParam(any(OrderInfo.class), any(OrderInfoQuery.class))).thenReturn(2);
        when(orderItemMapper.selectList(any(OrderItemQuery.class))).thenAnswer(invocation -> {
            String orderId = invocation.getArgument(0, OrderItemQuery.class).getOrderId();
            return List.of(item(orderId, orderId.equals("order-1") ? "p1" : "p2"));
        });
        when(orderCouponRelMapper.selectList(any(OrderCouponRelQuery.class))).thenReturn(List.of());

        service.cancelOrder("user-1", "order-1", OrderStatusEnum.WAIT_PAYMENT);

        ArgumentCaptor<OrderInfo> updateCaptor = ArgumentCaptor.forClass(OrderInfo.class);
        ArgumentCaptor<OrderInfoQuery> queryCaptor = ArgumentCaptor.forClass(OrderInfoQuery.class);
        verify(orderInfoMapper).updateByParam(updateCaptor.capture(), queryCaptor.capture());
        assertEquals(OrderStatusEnum.CANCELLED.getStatus(), updateCaptor.getValue().getOrderStatus());
        assertEquals("pay-1", queryCaptor.getValue().getPayOrderId());
        assertEquals(OrderStatusEnum.WAIT_PAYMENT.getStatus(), queryCaptor.getValue().getOrderStatus());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<ProductItem>> itemsCaptor = ArgumentCaptor.forClass(List.class);
        verify(stockRpcSupport).restoreOrderStock(org.mockito.ArgumentMatchers.eq("pay-1"), itemsCaptor.capture());
        assertEquals(2, itemsCaptor.getValue().size());
        verify(payRpcSupport).markClosed("pay-1");
    }

	@Test
	void channelCloseFailureDoesNotBlockCouponReleaseOrStockRestore() {
		// 契约（2026-10-16 审计 H1 后）：本地关单事实已提交，远程收敛的每一步都必须独立容错。
		// 此前渠道关单抛错会直接跳过解券与库存回补，而重试又因状态已 CANCELLED 短路，
		// 造成库存永久虚少、券永久 CANT 且无台账。
		OrderInfo order = order("order-1", "pay-1", OrderStatusEnum.WAIT_PAYMENT);
		order.setPayChannel("mock");
		when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(order);
		when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(order));
		when(orderInfoMapper.updateByParam(any(OrderInfo.class), any(OrderInfoQuery.class))).thenReturn(1);
		when(orderItemMapper.selectList(any(OrderItemQuery.class)))
				.thenReturn(List.of(item("order-1", "p1")));
		when(orderCouponRelMapper.selectList(any(OrderCouponRelQuery.class))).thenReturn(List.of());
		doThrow(new BusinessException("渠道关单超时"))
				.when(payRpcSupport).closeOrder("pay-1", "mock");

		assertDoesNotThrow(() ->
				service.cancelOrder("user-1", "order-1", OrderStatusEnum.WAIT_PAYMENT),
				"渠道侧失败不应把整个取消流程打回（本地已取消）");
		verify(stockRpcSupport).restoreOrderStock(eq("pay-1"), any());
		verify(payRpcSupport).markClosed("pay-1");
	}

    @Test
    void repeatedCancellationOfClosedAggregateIsANoOp() {
        OrderInfo first = order("order-1", "pay-1", OrderStatusEnum.CANCELLED);
        OrderInfo second = order("order-2", "pay-1", OrderStatusEnum.CANCELLED);
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(first);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(first, second));

        service.cancelOrder("user-1", "order-1", OrderStatusEnum.WAIT_PAYMENT);

        verify(orderInfoMapper, never()).updateByParam(any(), any());
        verify(stockRpcSupport, never()).restoreOrderStock(anyString(), any());
        verify(payRpcSupport, never()).markClosed(anyString());
    }

    @Test
    void paidSiblingPreventsAggregateCancellation() {
        OrderInfo first = order("order-1", "pay-1", OrderStatusEnum.WAIT_PAYMENT);
        OrderInfo second = order("order-2", "pay-1", OrderStatusEnum.PAID);
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(first);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(first, second));

        assertThrows(RuntimeException.class,
                () -> service.cancelOrder("user-1", "order-1", OrderStatusEnum.WAIT_PAYMENT));

        verify(orderInfoMapper, never()).updateByParam(any(), any());
        verify(stockRpcSupport, never()).restoreOrderStock(anyString(), any());
    }

    @Test
    void staleRedisCloseMarkerCannotOverrideWaitingDatabaseState() {
        OrderInfo waiting = order("order-1", "pay-1", OrderStatusEnum.WAIT_PAYMENT);
        when(orderInfoMapper.selectList(any(OrderInfoQuery.class))).thenReturn(List.of(waiting));
        PayOrderNotifyDTO notification = new PayOrderNotifyDTO("pay-1", "channel-1");
        // 支付冲突处理已随批次二拆分移入 OrderPaymentService
        OrderPaymentService paymentService = new OrderPaymentService(orderInfoMapper, orderItemMapper,
                null, null, transactionTemplate, null, null, payOrderRedisComponent,
                payRpcSupport, null, null, null);

        assertThrows(RuntimeException.class, () -> ReflectionTestUtils.invokeMethod(
                paymentService, "handlePaySuccessConflict", "pay-1", notification));

        verify(payOrderRedisComponent, never()).isPayOrderCloseMarked(anyString());
        verify(payRpcSupport, never()).markRefunded(anyString());
    }

    private static OrderInfo order(String orderId, String payOrderId, OrderStatusEnum status) {
        OrderInfo order = new OrderInfo();
        order.setOrderId(orderId);
        order.setPayOrderId(payOrderId);
        order.setUserId("user-1");
        order.setOrderStatus(status.getStatus());
        return order;
    }

    private static OrderItem item(String orderId, String productId) {
        OrderItem item = new OrderItem();
        item.setOrderId(orderId);
        item.setOrderItemId(orderId + "-item");
        item.setProductId(productId);
        item.setPropertyValueIdHash(productId + "-sku");
        item.setBuyCount(1);
        return item;
    }
}
