package com.smartlect.biz;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.security.DelegatedUserIdentity;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.RequestFingerprint;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Separates accepted commands from current payment/refund/stock business outcomes. */
@Service
public class CommerceV2Service {
    public record Params(String orderId, String orderItemId, String payOrderId,
                         Long refundAmountCents, String reason) { }
    public record Action(String actionType, Params params) { }
    public record Status(String actionType, String idempotencyKey, Params params) { }

    private final OrderRequestIdempotencyService idempotency;
    private final OrderInfoService orders;
    private final OrderItemService items;
    private final RefundSagaService refunds;
    private final RefundSagaTransactionService refundTransactions;
    private final StockRpcSupport stocks;
    private final PayRpcSupport payments;

    public CommerceV2Service(OrderRequestIdempotencyService idempotency, OrderInfoService orders,
                            OrderItemService items, RefundSagaService refunds,
                            RefundSagaTransactionService refundTransactions,
                            StockRpcSupport stocks, PayRpcSupport payments) {
        this.idempotency = idempotency;
        this.orders = orders;
        this.items = items;
        this.refunds = refunds;
        this.refundTransactions = refundTransactions;
        this.stocks = stocks;
        this.payments = payments;
    }

    public Map<String, Object> execute(String userId, Action action, String key) {
        Map<String, Object> arguments = actionArguments(action);
        String command = command(action.actionType());
        try {
            Map<String, Object> receipt = idempotency.executeMap(userId, command, key, arguments, () -> {
                if ("CANCEL_ORDER".equals(action.actionType())) {
                    orders.cancelOrder(userId, (String) arguments.get("orderId"), OrderStatusEnum.WAIT_PAYMENT);
                } else {
                    refunds.requestConfirmedRefund((String) arguments.get("orderItemId"), userId,
                            (Long) arguments.get("refundAmountCents"));
                }
                Map<String, Object> accepted = result("command_accepted", "操作已受理，正在核对业务结果");
                accepted.putAll(arguments);
                return accepted;
            });
            Map<String, Object> current = status(userId, new Status(action.actionType(), key, action.params()));
            current.put("idempotencyReplayed", receipt.get("idempotencyReplayed"));
            return current;
        } catch (RuntimeException error) {
            // A refund request may commit before the provider fails; recover that fact.
            if (error instanceof HttpBusinessException) throw error;
            Map<String, Object> current = status(userId, new Status(action.actionType(), key, action.params()));
            if (Set.of("business_pending", "business_completed").contains(current.get("commandStatus"))) return current;
            throw error;
        }
    }

    public Map<String, Object> status(String userId, Status request) {
        if (request == null || request.actionType() == null) invalid();
        if ("PAYMENT".equals(request.actionType())) {
            String payOrderId = request.params() == null ? null : request.params().payOrderId();
            requireId(payOrderId);
            return paymentStatus(userId, payOrderId);
        }
        String command = command(request.actionType());
        idempotency.validateKey(request.idempotencyKey());
        OrderRequestIdempotency ledger = idempotency.find(userId, command, request.idempotencyKey());
        if (ledger == null) {
            // A concurrent uncommitted insert is not visible. Reusing the SAME key still
            // serializes on the unique ledger constraint; this never permits a new key.
            Map<String, Object> absent = result("unknown", "未找到已提交的原命令记录");
            absent.put("status", "NOT_FOUND");
            absent.put("commandFound", false);
            return absent;
        }
        Map<String, Object> outcome;
        if ("CREATE_ORDER".equals(request.actionType())) {
            outcome = createdOrder(userId, ledger);
        } else {
            Map<String, Object> args = actionArguments(new Action(request.actionType(), request.params()));
            if (!RequestFingerprint.sha256(args).equals(ledger.getRequestHash())) {
                throw new HttpBusinessException(409, "IDEMPOTENCY_ARGUMENT_MISMATCH");
            }
            outcome = "REFUND".equals(request.actionType())
                    ? refundStatus(userId, (String) args.get("orderItemId"))
                    : cancellationStatus(userId, (String) args.get("orderId"));
            if ("unknown".equals(outcome.get("commandStatus")) && "FAILED".equals(ledger.getStatus())) {
                outcome = result("rejected", "原命令未完成，请核对后重新确认");
            }
        }
        outcome.put("commandFound", true);
        outcome.put("commandLedgerStatus", ledger.getStatus());
        return outcome;
    }

    private Map<String, Object> createdOrder(String userId, OrderRequestIdempotency ledger) {
        if (!"COMPLETED".equals(ledger.getStatus()) || ledger.getResponseJson() == null) {
            return result("FAILED".equals(ledger.getStatus()) ? "rejected" : "unknown", "原建单命令尚无确定回执");
        }
        PayInfoDTO pay = JsonUtils.parseObject(ledger.getResponseJson(), PayInfoDTO.class);
        if (pay == null || pay.getPayOrderId() == null) return result("unknown", "建单回执缺少支付单标识");
        List<OrderInfo> found = ownedPaymentOrders(userId, pay.getPayOrderId());
        if (found.isEmpty()) return result("unknown", "建单回执与订单尚未核对一致");
        Map<String, Object> result = created(pay);
        result.put("orders", found.stream().map(order -> Map.of(
                "orderId", order.getOrderId(), "orderStatus", order.getOrderStatus())).toList());
        result.put("paymentStatus", payments.tradeStatus(userId, pay.getPayOrderId()).get("paymentStatus"));
        return result;
    }

    public static Map<String, Object> created(PayInfoDTO pay) {
        Map<String, Object> result = result("business_completed", "订单已创建，付款需另行确认");
        result.put("payOrderId", pay.getPayOrderId());
        result.put("amountCents", OrderQuoteService.cents(pay.getAmount()));
        result.put("paymentStatus", Boolean.TRUE.equals(pay.getIdempotencyReplayed()) ? "UNKNOWN" : "PENDING");
        result.put("idempotencyReplayed", Boolean.TRUE.equals(pay.getIdempotencyReplayed()));
        return result;
    }

    public Map<String, Object> paymentStatus(String userId, String payOrderId) {
        List<OrderInfo> found = ownedPaymentOrders(userId, payOrderId);
        if (found.isEmpty()) return result("unknown", "未找到本人支付单关联订单");
        Map<String, Object> pay = payments.tradeStatus(userId, payOrderId);
        String state = String.valueOf(pay.get("paymentStatus"));
        boolean paid = "PAID".equals(state) || "REFUNDED".equals(state);
        Set<Integer> synchronizedStates = Set.of(OrderStatusEnum.PAID.getStatus(), OrderStatusEnum.SHIPPED.getStatus(),
                OrderStatusEnum.COMPLETED.getStatus(), OrderStatusEnum.PARTIALLY_REFUNDED.getStatus(),
                OrderStatusEnum.REFUNDED.getStatus());
        boolean synced = paid && found.stream().allMatch(order -> synchronizedStates.contains(order.getOrderStatus()));
        String outcome = synced ? "business_completed" : "CLOSED".equals(state) ? "rejected"
                : paid || "PENDING".equals(state) ? "business_pending" : "unknown";
        Map<String, Object> result = result(outcome, synced ? "付款与订单状态已同步"
                : paid ? "模拟渠道已付款，订单尚待同步" : "付款尚未完成");
        result.putAll(pay);
        result.put("orderSynchronized", synced);
        result.put("orders", found.stream().map(order -> Map.of(
                "orderId", order.getOrderId(), "orderStatus", order.getOrderStatus())).toList());
        return result;
    }

    public Map<String, Object> refundStatus(String userId, String itemId) {
        OrderItem item = items.getOrderItemByOrderItemId(itemId);
        if (item == null) return result("unknown", "退款明细不存在");
        requireOrder(userId, item.getOrderId());
        RefundRequest refund = refundTransactions.findByOrderItemId(itemId);
        if (refund == null) return result("unknown", "尚无退款申请记录");
        DelegatedUserIdentity.requireOwner(userId, refund.getUserId());
        String state = refund.getStatus();
        String outcome = "COMPLETED".equals(state) ? "business_completed"
                : "REJECTED".equals(state) ? "rejected" : "business_pending";
        Map<String, Object> result = result(outcome, "COMPLETED".equals(state) ? "退款已完成"
                : "REJECTED".equals(state) ? "退款申请已驳回" : "退款已受理，尚未完成");
        result.put("refundStatus", state);
        result.put("refundRequestId", refund.getRefundRequestId());
        result.put("refundAmountCents", OrderQuoteService.cents(refund.getRefundAmount()));
        return result;
    }

    public Map<String, Object> cancellationStatus(String userId, String orderId) {
        OrderInfo order = requireOrder(userId, orderId);
        if (!OrderStatusEnum.CANCELLED.getStatus().equals(order.getOrderStatus())) {
            return result("unknown", "尚未观察到取消订单结果");
        }
        String reference = order.getPayOrderId();
        List<OrderInfo> cancelled = reference == null || reference.isBlank()
                ? List.of(order) : ownedPaymentOrders(userId, reference);
        List<ProductItem> expected = new ArrayList<>();
        for (OrderInfo suborder : cancelled) {
            if (!OrderStatusEnum.CANCELLED.getStatus().equals(suborder.getOrderStatus())) {
                return result("business_pending", "支付单内订单状态尚未一致");
            }
            OrderItemQuery query = new OrderItemQuery();
            query.setOrderId(suborder.getOrderId());
            for (OrderItem item : items.findListByParam(query)) {
                ProductItem sku = new ProductItem();
                sku.setProductId(item.getProductId());
                sku.setPropertyValueIdHash(item.getPropertyValueIdHash());
                sku.setBuyCount(item.getBuyCount());
                expected.add(sku);
            }
        }
        boolean restored = !expected.isEmpty() && stocks.isOrderStockApplied(
                reference == null || reference.isBlank() ? orderId : reference, expected);
        Map<String, Object> result = result(restored ? "business_completed" : "business_pending",
                restored ? "订单已取消且库存已恢复" : "订单已取消，库存恢复尚待确认");
        result.put("orderId", orderId);
        result.put("stockRestored", restored);
        return result;
    }

    private OrderInfo requireOrder(String userId, String orderId) {
        OrderInfo order = orders.getOrderInfoByOrderId(orderId);
        if (order == null) throw new HttpBusinessException(404, "ORDER_NOT_FOUND");
        DelegatedUserIdentity.requireOwner(userId, order.getUserId());
        return order;
    }

    private List<OrderInfo> ownedPaymentOrders(String userId, String payOrderId) {
        OrderInfoQuery query = new OrderInfoQuery();
        query.setPayOrderId(payOrderId);
        List<OrderInfo> found = orders.findListByParam(query);
        for (OrderInfo order : found) DelegatedUserIdentity.requireOwner(userId, order.getUserId());
        return found;
    }

    private static Map<String, Object> actionArguments(Action action) {
        if (action == null || action.params() == null || action.actionType() == null) invalid();
        Params params = action.params();
        Map<String, Object> result = new LinkedHashMap<>();
        if ("CANCEL_ORDER".equals(action.actionType())) {
            requireId(params.orderId());
            if (params.orderItemId() != null || params.payOrderId() != null
                    || params.refundAmountCents() != null || params.reason() != null) invalid();
            result.put("orderId", params.orderId());
        } else if ("REFUND".equals(action.actionType())) {
            requireId(params.orderItemId());
            if (params.orderId() != null || params.payOrderId() != null || params.refundAmountCents() == null
                    || params.refundAmountCents() < 0 || (params.reason() != null && params.reason().length() > 500)) invalid();
            result.put("orderItemId", params.orderItemId());
            result.put("refundAmountCents", params.refundAmountCents());
            if (params.reason() != null) result.put("reason", params.reason());
        } else invalid();
        return result;
    }

    private static String command(String actionType) {
        if (actionType == null) invalid();
        return switch (actionType) {
            case "CREATE_ORDER" -> OrderRequestIdempotencyService.COMMAND_POST_ORDER_V2;
            case "CANCEL_ORDER" -> OrderRequestIdempotencyService.COMMAND_COMMERCE_CANCEL_ORDER;
            case "REFUND" -> OrderRequestIdempotencyService.COMMAND_COMMERCE_REFUND;
            default -> throw new HttpBusinessException(400, "UNSUPPORTED_ACTION");
        };
    }

    private static Map<String, Object> result(String commandStatus, String message) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("commandStatus", commandStatus);
        result.put("status", switch (commandStatus) {
            case "business_completed" -> "SUCCESS";
            case "rejected" -> "FAILED";
            case "unknown" -> "UNKNOWN";
            default -> "PROCESSING";
        });
        result.put("resultMessage", message);
        return result;
    }

    private static void requireId(String id) { if (id == null || id.isBlank() || id.length() > 64) invalid(); }
    private static void invalid() { throw new HttpBusinessException(400, "INVALID_ACTION_ARGUMENTS"); }
}
