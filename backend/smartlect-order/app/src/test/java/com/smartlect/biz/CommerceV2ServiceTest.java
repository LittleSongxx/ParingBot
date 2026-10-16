package com.smartlect.biz;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.RequestFingerprint;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class CommerceV2ServiceTest {
    private static final String KEY = "confirmed-command-001";
    @Mock private OrderRequestIdempotencyService idempotency;
    @Mock private OrderInfoService orders;
    @Mock private OrderItemService items;
    @Mock private RefundSagaService refunds;
    @Mock private RefundSagaTransactionService refundTransactions;
    @Mock private StockRpcSupport stocks;
    @Mock private PayRpcSupport payments;
    @InjectMocks private CommerceV2Service service;

    @Test
    void completedCommandLedgerDoesNotTurnPendingRefundIntoCompletedMoney() {
        Map<String, Object> args = Map.of("orderItemId", "i1", "refundAmountCents", 1000L);
        when(idempotency.find("u1", OrderRequestIdempotencyService.COMMAND_COMMERCE_REFUND, KEY))
                .thenReturn(ledger(args, "COMPLETED"));
        OrderItem item = new OrderItem();
        item.setOrderId("o1");
        when(items.getOrderItemByOrderItemId("i1")).thenReturn(item);
        when(orders.getOrderInfoByOrderId("o1")).thenReturn(order(OrderStatusEnum.PAID));
        RefundRequest refund = new RefundRequest();
        refund.setUserId("u1");
        refund.setRefundRequestId("r1");
        refund.setRefundAmount(new BigDecimal("10.00"));
        refund.setStatus("STOCK_PENDING");
        when(refundTransactions.findByOrderItemId("i1")).thenReturn(refund);
        CommerceV2Service.Status request = new CommerceV2Service.Status("REFUND", KEY,
                new CommerceV2Service.Params(null, "i1", null, 1000L, null));
        assertEquals("business_pending", service.status("u1", request).get("commandStatus"));
        refund.setStatus("COMPLETED");
        assertEquals("business_completed", service.status("u1", request).get("commandStatus"));
        refund.setStatus("REJECTED");
        assertEquals("rejected", service.status("u1", request).get("commandStatus"));
        verifyNoInteractions(refunds);
    }

    @Test
    void cancellationRequiresStockRestorationNotJustCancelledOrder() {
        when(idempotency.find("u1", OrderRequestIdempotencyService.COMMAND_COMMERCE_CANCEL_ORDER, KEY))
                .thenReturn(ledger(Map.of("orderId", "o1"), "COMPLETED"));
        OrderInfo order = order(OrderStatusEnum.CANCELLED);
        when(orders.getOrderInfoByOrderId("o1")).thenReturn(order);
        when(orders.findListByParam(any())).thenReturn(List.of(order));
        OrderItem item = new OrderItem();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku1");
        item.setBuyCount(2);
        when(items.findListByParam(any())).thenReturn(List.of(item));
        when(stocks.isOrderStockApplied(eq("pay1"), anyList())).thenReturn(false, true);
        CommerceV2Service.Status request = new CommerceV2Service.Status("CANCEL_ORDER", KEY,
                new CommerceV2Service.Params("o1", null, null, null, null));
        Map<String, Object> pending = service.status("u1", request);
        assertEquals("business_pending", pending.get("commandStatus"));
        assertEquals(false, pending.get("stockRestored"));
        assertEquals("business_completed", service.status("u1", request).get("commandStatus"));
    }

    @Test
    void paymentSeparatesSettledIntentFromOrderSynchronizationAndChecksOwner() {
        OrderInfo order = order(OrderStatusEnum.WAIT_PAYMENT);
        when(orders.findListByParam(any())).thenReturn(List.of(order));
        when(payments.tradeStatus("u1", "pay1")).thenReturn(Map.of("paymentStatus", "PAID", "amountCents", 1000L));
        var pending = service.paymentStatus("u1", "pay1");
        assertEquals("business_pending", pending.get("commandStatus"));
        assertEquals(false, pending.get("orderSynchronized"));
        order.setOrderStatus(OrderStatusEnum.PAID.getStatus());
        assertEquals("business_completed", service.paymentStatus("u1", "pay1").get("commandStatus"));
        assertThrows(HttpBusinessException.class, () -> service.paymentStatus("other", "pay1"));
        verify(payments, never()).tradeStatus(eq("other"), any());
    }

    @Test
    void createRecoveryUsesOriginalKeyWithoutQuoteOrNewCommandAndDistinguishesNotFound() {
        CommerceV2Service.Status request = new CommerceV2Service.Status("CREATE_ORDER", KEY, null);
        assertEquals("NOT_FOUND", service.status("u1", request).get("status"));
        OrderRequestIdempotency ledger = ledger(Map.of(), "PROCESSING");
        when(idempotency.find("u1", OrderRequestIdempotencyService.COMMAND_POST_ORDER_V2, KEY)).thenReturn(ledger);
        assertEquals("unknown", service.status("u1", request).get("commandStatus"));
        ledger.setStatus("COMPLETED");
        ledger.setResponseJson(JsonUtils.toJson(new PayInfoDTO(null, "pay1", new BigDecimal("10.00"))));
        when(orders.findListByParam(any())).thenReturn(List.of(order(OrderStatusEnum.PAID)));
        when(payments.tradeStatus("u1", "pay1")).thenReturn(Map.of("paymentStatus", "PAID"));
        var restored = service.status("u1", request);
        assertEquals("pay1", restored.get("payOrderId"));
        assertEquals("business_completed", restored.get("commandStatus"));
        verifyNoInteractions(refunds, stocks);
        assertThrows(HttpBusinessException.class, () -> service.execute("u1",
                new CommerceV2Service.Action("PAYMENT", new CommerceV2Service.Params(null, null, "pay1", null, null)), KEY));
    }

    @Test
    void statusRejectsDifferentTargetForSameCommandKey() {
        when(idempotency.find("u1", OrderRequestIdempotencyService.COMMAND_COMMERCE_CANCEL_ORDER, KEY))
                .thenReturn(ledger(Map.of("orderId", "original"), "COMPLETED"));
        assertThrows(HttpBusinessException.class, () -> service.status("u1", new CommerceV2Service.Status(
                "CANCEL_ORDER", KEY, new CommerceV2Service.Params("different", null, null, null, null))));
        verifyNoInteractions(orders, items, stocks);
    }

    private static OrderInfo order(OrderStatusEnum status) {
        OrderInfo order = new OrderInfo();
        order.setOrderId("o1");
        order.setPayOrderId("pay1");
        order.setUserId("u1");
        order.setOrderStatus(status.getStatus());
        return order;
    }

    private static OrderRequestIdempotency ledger(Map<String, Object> args, String status) {
        OrderRequestIdempotency ledger = new OrderRequestIdempotency();
        ledger.setStatus(status);
        ledger.setRequestHash(RequestFingerprint.sha256(args));
        return ledger;
    }
}
