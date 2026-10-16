package com.smartlect.controller.internal;

import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.biz.CommerceActionStatusService;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderItemService;
import com.smartlect.biz.OrderLogisticsInfoService;
import com.smartlect.biz.RefundSagaTransactionService;
import com.smartlect.controller.ABaseController;
import com.smartlect.security.DelegatedUserIdentity;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.query.SafeSort;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.PageUtils;
import com.smartlect.utils.StringTools;
import com.smartlect.utils.RequestFingerprint;
import com.smartlect.mappers.OrderItemMapper;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/internal/order/commerce")
public class OrderCommerceInternalController extends ABaseController {

    private static final DateTimeFormatter DT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final String ACTION_SNAPSHOT_VERSION = "order-action-snapshot/v1";

    @Resource
    private OrderInfoService orderInfoService;
    @Resource
    private OrderItemService orderItemService;
    @Resource
    private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    @Resource
    private OrderLogisticsInfoService orderLogisticsInfoService;
    @Resource
    private CommerceActionStatusService commerceActionStatusService;
    @Resource
    private RefundSagaTransactionService refundSagaTransactionService;

    @PostMapping("/listOrders")
    public ResponseVO<List<Map<String, Object>>> listOrders(@RequestBody Map<String, Object> body) {
        // 身份以委托头为准，body 里的 userId 必须与之一致（防模型改 body 换身份）。
        String userId = DelegatedUserIdentity.requireAndMatch(body.get("userId"));
        OrderInfoQuery query = new OrderInfoQuery();
        query.setUserId(userId);
        query.setQueryItems(true);
        query.setOrderBy(SafeSort.of("o.order_time desc"));
        String orderId = str(body, "orderId");
        if (!StringTools.isEmpty(orderId)) {
            query.setOrderId(orderId);
        }
        query.setOrderStatusList(new Integer[]{
                OrderStatusEnum.WAIT_PAYMENT.getStatus(),
                OrderStatusEnum.PAID.getStatus(),
                OrderStatusEnum.SHIPPED.getStatus(),
                OrderStatusEnum.COMPLETED.getStatus(),
                OrderStatusEnum.CANCELLED.getStatus(),
                OrderStatusEnum.CLOSED.getStatus(),
                OrderStatusEnum.REFUNDED.getStatus(),
                OrderStatusEnum.PARTIALLY_REFUNDED.getStatus()
        });
        int limit = intVal(body.get("limit"), 30);
        // time range: filter in memory after query if needed (mapper may lack timeStart)
        List<OrderInfo> list = PageUtils.pageInfo(1, limit,
                () -> orderInfoService.findListByParam(query)).getList();
        String timeStart = str(body, "timeStart");
        String timeEnd = str(body, "timeEnd");
        List<Map<String, Object>> result = new ArrayList<>();
        for (OrderInfo o : list) {
            if (!inTimeRange(o.getOrderTime(), timeStart, timeEnd)) {
                continue;
            }
            result.add(toOrderMap(o, true));
        }
        return getSuccessResponseVO(result);
    }

    @PostMapping("/getOrder")
    public ResponseVO<Map<String, Object>> getOrder(@RequestBody Map<String, Object> body) {
        String orderId = str(body, "orderId");
        if (StringTools.isEmpty(orderId)) {
            return getSuccessResponseVO(null);
        }
        String userId = DelegatedUserIdentity.require();
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
        if (order == null) {
            return getSuccessResponseVO(null);
        }
        DelegatedUserIdentity.requireOwner(userId, order.getUserId());
        OrderItemQuery iq = new OrderItemQuery();
        iq.setOrderId(orderId);
        order.setOrderItemList(orderItemService.findListByParam(iq));
        return getSuccessResponseVO(toOrderMap(order, true));
    }

    @PostMapping("/getOrderItem")
    public ResponseVO<Map<String, Object>> getOrderItem(@RequestBody Map<String, Object> body) {
        String orderItemId = str(body, "orderItemId");
        if (StringTools.isEmpty(orderItemId)) {
            return getSuccessResponseVO(null);
        }
        String userId = DelegatedUserIdentity.require();
        OrderItem item = orderItemService.getOrderItemByOrderItemId(orderItemId);
        if (item == null) {
            return getSuccessResponseVO(null);
        }
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(item.getOrderId());
        DelegatedUserIdentity.requireOwner(userId, order == null ? null : order.getUserId());
        return getSuccessResponseVO(toItemMap(item));
    }

    @PostMapping("/listOrderItems")
    public ResponseVO<List<Map<String, Object>>> listOrderItems(@RequestBody Map<String, Object> body) {
        String orderId = str(body, "orderId");
        if (StringTools.isEmpty(orderId)) {
            return getSuccessResponseVO(Collections.emptyList());
        }
        String userId = DelegatedUserIdentity.require();
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
        DelegatedUserIdentity.requireOwner(userId, order == null ? null : order.getUserId());
        OrderItemQuery iq = new OrderItemQuery();
        iq.setOrderId(orderId);
        iq.setOrderBy(SafeSort.of("order_item_id asc"));
        List<OrderItem> items = orderItemService.findListByParam(iq);
        List<Map<String, Object>> result = new ArrayList<>();
        if (items != null) {
            for (OrderItem item : items) {
                result.add(toItemMap(item));
            }
        }
        return getSuccessResponseVO(result);
    }

    @PostMapping("/getLogistics")
    public ResponseVO<Map<String, Object>> getLogistics(@RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.requireAndMatch(body.get("userId"));
        String orderId = str(body, "orderId");
        if (StringTools.isEmpty(orderId)) {
            return getSuccessResponseVO(null);
        }
        OrderLogisticsInfo info;
        try {
            info = orderLogisticsInfoService.getOrderLogisticsRecords(userId, orderId);
        } catch (Exception e) {
            return getSuccessResponseVO(null);
        }
        if (info == null) {
            return getSuccessResponseVO(null);
        }
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("orderId", info.getOrderId());
        map.put("userId", info.getUserId());
        map.put("logisticsNo", info.getLogisticsNo());
        map.put("logisticsCompany", info.getLogisticsCompany());
        map.put("logisticsStatus", info.getLogisticsStatus());
        map.put("receiverName", info.getReceiverName());
        map.put("receiverPhone", info.getReceiverPhone());
        map.put("receiverAddress", info.getReceiverAddress());
        map.put("recordList", info.getRecordList());
        return getSuccessResponseVO(map);
    }

    @PostMapping("/refundStatus")
    public ResponseVO<List<Map<String, Object>>> refundStatus(@RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.requireAndMatch(body.get("userId"));
        String orderId = str(body, "orderId");
        String orderItemId = str(body, "orderItemId");
        if (StringTools.isEmpty(orderId) && StringTools.isEmpty(orderItemId)) {
            return getSuccessResponseVO(Collections.emptyList());
        }

        List<RefundRequest> requests = new ArrayList<>();
        if (!StringTools.isEmpty(orderItemId)) {
            RefundRequest request = refundSagaTransactionService.findByOrderItemId(orderItemId);
            if (request != null && userId.equals(request.getUserId())) {
                requests.add(request);
            }
        } else {
            OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
            if (order == null || !userId.equals(order.getUserId())) {
                return getSuccessResponseVO(Collections.emptyList());
            }
            OrderItemQuery itemQuery = new OrderItemQuery();
            itemQuery.setOrderId(orderId);
            List<OrderItem> items = orderItemService.findListByParam(itemQuery);
            if (items != null && !items.isEmpty()) {
                // 批量取退款单：此前逐明细查一次，多明细订单会放大成 N 次 SQL（N+1）
                Map<String, RefundRequest> byItem = refundSagaTransactionService.mapByOrderItemIds(
                        items.stream().map(OrderItem::getOrderItemId).toList());
                for (OrderItem item : items) {
                    RefundRequest request = byItem.get(item.getOrderItemId());
                    if (request != null && userId.equals(request.getUserId())) {
                        requests.add(request);
                    }
                }
            }
        }
        return getSuccessResponseVO(requests.stream()
                .map(this::toRefundStatusMap)
                .collect(Collectors.toList()));
    }

    @PostMapping("/actionStatus")
    public ResponseVO<Map<String, Object>> actionStatus(
            @RequestBody Map<String, Object> body) {
        // 幂等核对也是用户数据操作：委托身份 + body 一致性一起校验。
        DelegatedUserIdentity.requireAndMatch(body.get("userId"));
        return getSuccessResponseVO(commerceActionStatusService.resolve(body));
    }

    /**
     * Read-only, server-owned action preflight for the Growth.
     *
     * This is intentionally an advisory decision, not a write reservation.
     * The real command remains responsible for its transactional/lock-aware
     * validation at execution time.  Keeping the decision in the order service
     * prevents the Python assistant service from inferring a capability from an order
     * status snapshot or from a retrieved policy sentence.
     */
    @PostMapping("/actionCapability")
    public ResponseVO<Map<String, Object>> actionCapability(
            @RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.require();
        String action = str(body, "action");
        String orderId = str(body, "orderId");
        String orderItemId = str(body, "orderItemId");
        if (StringTools.isEmpty(action) || StringTools.isEmpty(orderId)) {
            return getSuccessResponseVO(capabilityResult(
                    "UNAVAILABLE", action, orderId, orderItemId,
                    "INVALID_REQUEST"));
        }
        action = action.trim().toUpperCase();
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
        if (order == null) {
            return getSuccessResponseVO(capabilityResult(
                    "DENIED", action, orderId, orderItemId, "ORDER_NOT_FOUND"));
        }
        DelegatedUserIdentity.requireOwner(userId, order.getUserId());
        OrderItem item = null;
        if (!StringTools.isEmpty(orderItemId)) {
            item = orderItemService.getOrderItemByOrderItemId(orderItemId);
            if (item == null || !orderId.equals(item.getOrderId())) {
                return getSuccessResponseVO(capabilityResult(
                        "DENIED", action, orderId, orderItemId, "ORDER_ITEM_MISMATCH"));
            }
        }
        return getSuccessResponseVO(evaluateActionCapability(
                action, order, item, orderId, orderItemId));
    }

    @PostMapping("/coPurchaseProductIds")
    public ResponseVO<List<String>> coPurchaseProductIds(@RequestBody Map<String, Object> body) {
        List<String> productIds = productIds(body, "productIds");
        List<String> excluded = productIds(body, "excludeProductIds");
        String productId = str(body, "productId");
        if (StringTools.isEmpty(productId) || (productIds != null && productIds.isEmpty())) {
            return getSuccessResponseVO(Collections.emptyList());
        }
        int limit = Math.min(Math.max(intVal(body.get("limit"), 5), 1), 20);

        return getSuccessResponseVO(orderItemMapper.selectCoPurchaseProductIds(productId, productIds, excluded, limit));
    }

    @PostMapping("/popularProducts")
    public ResponseVO<List<Map<String, Object>>> popularProducts(@RequestBody Map<String, Object> body) {
        List<String> productIds = productIds(body, "productIds");
        List<String> excluded = productIds(body, "excludeProductIds");
        Object requestedLimit = body.getOrDefault("limit", 20);
        if (!(requestedLimit instanceof Integer limit) || limit < 1 || limit > 20) {
            throw new BusinessException(400, "invalid_limit");
        }
        if (productIds != null && productIds.isEmpty()) return getSuccessResponseVO(List.of());
        List<Map<String, Object>> result = new ArrayList<>();
        String observedAt = Instant.now().toString();
        for (Map<String, Object> row : orderItemMapper.selectPopularProducts(productIds, excluded, limit)) {
            result.add(Map.of("productId", row.get("productId"),
                    "paidUnits", new BigDecimal(row.get("paidUnits").toString()).longValueExact(),
                    "basis", "confirmed_payment_units_excluding_refunds", "observedAt", observedAt));
        }
        return getSuccessResponseVO(result);
    }

    private static List<String> productIds(Map<String, Object> body, String key) {
        if (!body.containsKey(key)) return null;
        if (!(body.get(key) instanceof List<?> values) || values.size() > 5000) {
            throw new BusinessException(400, "invalid_" + key);
        }
        List<String> ids = new ArrayList<>(values.size());
        for (Object value : values) {
            if (!(value instanceof String id) || id.isBlank() || id.length() > 64 || id.indexOf('\0') >= 0) {
                throw new BusinessException(400, "invalid_" + key);
            }
            ids.add(id);
        }
        return ids;
    }

    private Map<String, Object> toOrderMap(OrderInfo o, boolean withItems) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("orderId", o.getOrderId());
        m.put("userId", o.getUserId());
        m.put("orderStatus", o.getOrderStatus());
        m.put("orderStatusName", orderStatusName(o.getOrderStatus()));
        m.put("amount", o.getAmount());
        m.put("payScene", o.getPayScene());
        m.put("payChannel", o.getPayChannel());
        m.put("payOrderId", o.getPayOrderId());
        m.put("orderTime", formatDate(o.getOrderTime()));
        m.put("subject", o.getSubject());
        if (withItems) {
            List<Map<String, Object>> items = new ArrayList<>();
            if (o.getOrderItemList() != null) {
                for (OrderItem item : o.getOrderItemList()) {
                    items.add(toItemMap(item));
                }
            }
            m.put("items", items);
        }
        return m;
    }

    private Map<String, Object> toItemMap(OrderItem item) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("orderId", item.getOrderId());
        m.put("orderItemId", item.getOrderItemId());
        m.put("productId", item.getProductId());
        m.put("productName", item.getProductName());
        m.put("cover", item.getCover());
        m.put("propertyInfo", item.getPropertyInfo());
        m.put("propertyValueIdHash", item.getPropertyValueIdHash());
        m.put("itemAmount", item.getItemAmount());
        m.put("paidAmount", item.getPaidAmount());
        m.put("refundedAmount", item.getRefundedAmount());
        m.put("buyCount", item.getBuyCount());
        m.put("orderItemStatus", item.getOrderItemStatus());
        return m;
    }

    private Map<String, Object> toRefundStatusMap(RefundRequest request) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("refundRequestId", request.getRefundRequestId());
        result.put("orderId", request.getOrderId());
        result.put("orderItemId", request.getOrderItemId());
        result.put("status", request.getStatus());
        result.put("statusName", refundStatusName(request.getStatus()));
        result.put("refundAmount", request.getRefundAmount());
        result.put("createdAt", formatDate(request.getCreatedAt()));
        result.put("completedAt", formatDate(request.getCompletedAt()));
        return result;
    }

    private static String refundStatusName(String status) {
        if (status == null) return "处理中";
        return switch (status) {
            case "PENDING_PAYMENT" -> "等待原路退款";
            case "PAYMENT_CONFIRMED" -> "退款资金已确认";
            case "STOCK_PENDING" -> "退款已受理，库存处理中";
            case "COMPLETED" -> "退款已完成";
            case "MANUAL_REVIEW" -> "退款需人工复核";
            case "REJECTED" -> "退款申请已驳回";
            default -> "退款处理中";
        };
    }

    private static Map<String, Object> capabilityResult(
            String decision,
            String action,
            String orderId,
            String orderItemId,
            String reasonCode) {
        return capabilityResult(decision, action, orderId, orderItemId, reasonCode, null, null);
    }

    private static Map<String, Object> capabilityResult(
            String decision,
            String action,
            String orderId,
            String orderItemId,
            String reasonCode,
            OrderInfo order,
            OrderItem item) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("decision", decision);
        result.put("action", action);
        result.put("orderId", orderId);
        result.put("orderItemId", StringTools.isEmpty(orderItemId) ? null : orderItemId);
        result.put("reasonCode", reasonCode);
        result.put("capabilityVersion", "order-action-capability/v1");
        Map<String, Object> snapshot = actionSnapshot(action, orderId, orderItemId, order, item);
        String snapshotHash = RequestFingerprint.sha256(snapshot);
        result.put("snapshotVersion", ACTION_SNAPSHOT_VERSION);
        // Keep both spellings: Java clients use the HTTP-style ETag spelling,
        // while the Python normalizer exposes the lower-camel alias.
        result.put("snapshotEtag", "sha256:" + snapshotHash);
        result.put("snapshotETag", "sha256:" + snapshotHash);
        result.put("snapshotHash", snapshotHash);
        result.put("snapshot", snapshot);
        result.put("evaluatedAt", formatDate(new Date()));
        return result;
    }

    private static Map<String, Object> evaluateActionCapability(
            String action,
            OrderInfo order,
            OrderItem item,
            String orderId,
            String orderItemId) {
        Integer status = order.getOrderStatus();
        return switch (action) {
            case "CANCEL_ORDER" -> capabilityResult(
                    OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(status)
                            ? "ALLOWED" : "DENIED",
                    action,
                    orderId,
                    orderItemId,
                    OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(status)
                            ? "ORDER_STATUS_CANCELLABLE"
                            : "ORDER_STATUS_NOT_CANCELLABLE",
                    order,
                    item);
            case "CONFIRM_RECEIPT" -> capabilityResult(
                    OrderStatusEnum.SHIPPED.getStatus().equals(status)
                                    || OrderStatusEnum.PARTIALLY_REFUNDED.getStatus().equals(status)
                            ? "ALLOWED" : "DENIED",
                    action,
                    orderId,
                    orderItemId,
                    OrderStatusEnum.SHIPPED.getStatus().equals(status)
                                    || OrderStatusEnum.PARTIALLY_REFUNDED.getStatus().equals(status)
                            ? "ORDER_STATUS_CONFIRMABLE"
                            : "ORDER_STATUS_NOT_CONFIRMABLE",
                    order,
                    item);
            // These conditions intentionally mirror the command services. Do
            // not add a synthetic order-status rule here.
            default -> capabilityResult(
                    "UNAVAILABLE", action, orderId, orderItemId, "UNSUPPORTED_ACTION",
                    order,
                    item);
        };
    }

    private static Map<String, Object> actionSnapshot(
            String action,
            String orderId,
            String orderItemId,
            OrderInfo order,
            OrderItem item) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("schemaVersion", ACTION_SNAPSHOT_VERSION);
        snapshot.put("action", action);
        snapshot.put("orderId", orderId);
        snapshot.put("orderItemId", StringTools.isEmpty(orderItemId) ? null : orderItemId);
        snapshot.put("orderStatus", order == null ? null : order.getOrderStatus());
        snapshot.put("payOrderIdPresent", order != null && !StringTools.isEmpty(order.getPayOrderId()));
        snapshot.put("orderItemStatus", item == null ? null : item.getOrderItemStatus());
        return snapshot;
    }

    private static String orderStatusName(Integer status) {
        if (status == null) {
            return null;
        }
        for (OrderStatusEnum value : OrderStatusEnum.values()) {
            if (value.getStatus().equals(status)) {
                return value.getDesc();
            }
        }
        return null;
    }

    private static boolean inTimeRange(Date orderTime, String timeStart, String timeEnd) {
        if (orderTime == null) {
            return true;
        }
        if (StringTools.isEmpty(timeStart) && StringTools.isEmpty(timeEnd)) {
            return true;
        }
        LocalDateTime t = LocalDateTime.ofInstant(orderTime.toInstant(), ZoneId.systemDefault());
        if (!StringTools.isEmpty(timeStart)) {
            LocalDateTime start = parseDt(timeStart, true);
            if (start != null && t.isBefore(start)) {
                return false;
            }
        }
        if (!StringTools.isEmpty(timeEnd)) {
            LocalDateTime end = parseDt(timeEnd, false);
            if (end != null && t.isAfter(end)) {
                return false;
            }
        }
        return true;
    }

    private static LocalDateTime parseDt(String s, boolean startOfDay) {
        try {
            String n = normalizeDt(s);
            if (n.length() == 10) {
                n = n + (startOfDay ? " 00:00:00" : " 23:59:59");
            }
            return LocalDateTime.parse(n, DT);
        } catch (Exception e) {
            return null;
        }
    }

    private static String normalizeDt(String s) {
        if (s == null) {
            return null;
        }
        return s.contains("T") ? s.replace('T', ' ') : s;
    }

    private static String formatDate(Date d) {
        if (d == null) {
            return null;
        }
        return DT.format(LocalDateTime.ofInstant(d.toInstant(), ZoneId.systemDefault()));
    }

    private static String str(Map<String, Object> body, String key) {
        if (body == null || body.get(key) == null) {
            return null;
        }
        return String.valueOf(body.get(key));
    }

    private static int intVal(Object v, int def) {
        if (v == null) {
            return def;
        }
        try {
            return Integer.parseInt(String.valueOf(v));
        } catch (Exception e) {
            return def;
        }
    }
}
