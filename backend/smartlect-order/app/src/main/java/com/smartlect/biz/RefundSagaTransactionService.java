package com.smartlect.biz;

import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.enums.RefundSagaStatus;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.RefundRequestMapper;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.support.MqIdempotencyKeys;
import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import java.util.Set;
import java.util.UUID;

@Service
@Slf4j
public class RefundSagaTransactionService {

    @Resource
    private RefundRequestMapper refundRequestMapper;
    @Resource
    private OrderInfoMapper<OrderInfo, ?> orderInfoMapper;
    @Resource
    private OrderItemMapper<OrderItem, ?> orderItemMapper;
    @Resource
    private TransactionalMqSender transactionalMqSender;
    @Resource
    private OrderStateMachine orderStateMachine;

    @Value("${refund.saga.retry-seconds:60}")
    private int retrySeconds;
    @Value("${refund.saga.max-retries:6}")
    private int maxRetries;

    @Transactional(rollbackFor = Exception.class)
    public RefundRequest createOrLoad(String orderItemId, String userId) {
        return createOrLoad(orderItemId, userId, null);
    }

    @Transactional(rollbackFor = Exception.class)
    public RefundRequest createOrLoadConfirmed(String orderItemId, String userId, long confirmedAmountCents) {
        return createOrLoad(orderItemId, userId, confirmedAmountCents);
    }

    private RefundRequest createOrLoad(String orderItemId, String userId, Long confirmedAmountCents) {
        RefundRequest existing = refundRequestMapper.selectByOrderItemId(orderItemId);
        if (existing != null) {
            assertOwner(existing, userId);
            assertConfirmedAmount(existing.getRefundAmount(), confirmedAmountCents);
            return existing;
        }

        OrderItem item = orderItemMapper.selectByOrderItemIdForUpdate(orderItemId);
        if (item == null) {
            throw new BusinessException("订单明细不存在");
        }
        OrderInfo order = orderInfoMapper.selectByOrderIdForUpdate(item.getOrderId());
        if (order == null || !userId.equals(order.getUserId())) {
            throw new BusinessException("订单不存在");
        }
        validateRefundable(order, item);
        assertConfirmedAmount(item.getRemainingRefundableAmount(), confirmedAmountCents);

        String requestId = stableRefundId(orderItemId);
        RefundRequest request = new RefundRequest();
        request.setRefundRequestId(requestId);
        request.setRefundOrderNo(requestId);
        request.setSourcePayOrderId(order.getPayOrderId());
        request.setOrderId(order.getOrderId());
        request.setOrderItemId(item.getOrderItemId());
        request.setUserId(userId);
        request.setProductId(item.getProductId());
        request.setPropertyValueIdHash(item.getPropertyValueIdHash());
        request.setBuyCount(item.getBuyCount());
        request.setRefundAmount(item.getRemainingRefundableAmount());
        request.setPayChannel(order.getPayChannel());
        request.setStatus(request.getRefundAmount().signum() == 0
                ? RefundSagaStatus.PAYMENT_CONFIRMED.name() : RefundSagaStatus.PENDING_PAYMENT.name());
        request.setRetryCount(0);
        request.setCreatedAt(new Date());
        request.setUpdatedAt(new Date());
        refundRequestMapper.insertIgnore(request);

        RefundRequest stored = refundRequestMapper.selectByOrderItemId(orderItemId);
        if (stored == null) {
            throw new BusinessException("退款请求创建失败");
        }
        assertOwner(stored, userId);
        assertConfirmedAmount(stored.getRefundAmount(), confirmedAmountCents);
        return stored;
    }

    private static void assertConfirmedAmount(BigDecimal actual, Long confirmed) {
        if (confirmed != null && (confirmed < 0 || actual == null || OrderQuoteService.cents(actual) != confirmed)) {
            OrderQuoteService.reconfirm();
        }
    }

    public RefundRequest get(String refundRequestId) {
        return refundRequestMapper.selectById(refundRequestId);
    }

    public RefundRequest findByOrderItemId(String orderItemId) {
        if (orderItemId == null || orderItemId.isBlank()) {
            return null;
        }
        return refundRequestMapper.selectByOrderItemId(orderItemId);
    }

    public List<RefundRequest> selectDue(int limit) {
        return refundRequestMapper.selectDue(Math.max(1, Math.min(limit, 100)));
    }

    @Transactional(rollbackFor = Exception.class)
    public boolean claimPaymentAttempt(String refundRequestId) {
        return refundRequestMapper.claimPaymentAttempt(refundRequestId, retrySeconds) == 1;
    }

    @Transactional(rollbackFor = Exception.class)
    public void markPaymentConfirmed(String refundRequestId) {
        refundRequestMapper.markPaymentConfirmed(refundRequestId);
    }

    @Transactional(rollbackFor = Exception.class)
    public void recordPaymentFailure(String refundRequestId, String error) {
        refundRequestMapper.recordPaymentFailure(
                refundRequestId, retrySeconds, maxRetries, truncate(error));
    }

    /** 驳回后用户重新申请：REJECTED → PENDING_PAYMENT 重走全流程（CAS 单次生效）。 */
    @Transactional(rollbackFor = Exception.class)
    public boolean resetRejected(String refundRequestId) {
        return refundRequestMapper.resetRejected(refundRequestId) == 1;
    }

    @Transactional(rollbackFor = Exception.class)
    public boolean queueStockRestore(String refundRequestId, boolean retry) {
        RefundRequest request = refundRequestMapper.selectByIdForUpdate(refundRequestId);
        if (request == null) {
            return false;
        }
        RefundSagaStatus status = RefundSagaStatus.valueOf(request.getStatus());
        if (status == RefundSagaStatus.COMPLETED
                || status == RefundSagaStatus.MANUAL_REVIEW
                || status == RefundSagaStatus.REJECTED) {
            return false;
        }

        int attempt = 0;
        if (status == RefundSagaStatus.PAYMENT_CONFIRMED) {
            finalizeOrderRefund(request);
            refundRequestMapper.markStockPending(refundRequestId, retrySeconds);
        } else if (status == RefundSagaStatus.STOCK_PENDING && retry) {
            if (request.getRetryCount() != null && request.getRetryCount() >= maxRetries) {
                refundRequestMapper.recordStockRetry(
                        refundRequestId, retrySeconds, maxRetries, "库存恢复重试已耗尽");
                return false;
            }
            refundRequestMapper.recordStockRetry(
                    refundRequestId, retrySeconds, maxRetries, "等待库存恢复确认");
            RefundRequest updated = refundRequestMapper.selectByIdForUpdate(refundRequestId);
            if (updated == null || RefundSagaStatus.MANUAL_REVIEW.name().equals(updated.getStatus())) {
                return false;
            }
            attempt = updated.getRetryCount() == null ? 1 : updated.getRetryCount();
        } else {
            return false;
        }

        RefundStockRestoreDTO payload = new RefundStockRestoreDTO();
        payload.setRefundRequestId(request.getRefundRequestId());
        payload.setBusinessKey(request.getRefundRequestId());
        payload.setProductId(request.getProductId());
        payload.setPropertyValueIdHash(request.getPropertyValueIdHash());
        payload.setChangeAmount(request.getBuyCount());
        transactionalMqSender.sendAfterCommit(
                RocketMqTopics.TOPIC_REFUND,
                RocketMqTopics.TAG_REFUND_STOCK,
                payload,
                MqIdempotencyKeys.refundStock(request.getRefundRequestId(), attempt),
                MessageReliabilityLevelEnum.STANDARD);
        return true;
    }

    @Transactional(rollbackFor = Exception.class)
    public void markCompleted(String refundRequestId) {
        RefundRequest request = refundRequestMapper.selectById(refundRequestId);
        if (request == null) {
            return;
        }
        boolean newlyCompleted = !RefundSagaStatus.COMPLETED.name().equals(request.getStatus());
        refundRequestMapper.markCompleted(refundRequestId);
        if (!newlyCompleted) {
            return;
        }
    }

    private void finalizeOrderRefund(RefundRequest request) {
        OrderItem item = orderItemMapper.selectByOrderItemIdForUpdate(request.getOrderItemId());
        OrderInfo order = orderInfoMapper.selectByOrderIdForUpdate(request.getOrderId());
        if (item == null || order == null) {
            throw new BusinessException("退款订单数据不存在");
        }
        if (!OrderItemStatusEnum.REFUND.getStatus().equals(item.getOrderItemStatus())) {
            BigDecimal remaining = item.getRemainingRefundableAmount();
            if (remaining == null || request.getRefundAmount() == null
                    || request.getRefundAmount().signum() < 0
                    || request.getRefundAmount().compareTo(remaining) > 0) {
                throw new BusinessException("退款金额超过订单明细剩余实付");
            }
            item.setRefundedAmount(item.getPaidAmount().subtract(remaining).add(request.getRefundAmount()));
            item.setOrderItemStatus(OrderItemStatusEnum.REFUND.getStatus());
            item.setRefundOrderId(request.getRefundOrderNo());
            if (!Integer.valueOf(1).equals(orderItemMapper.updateByOrderItemId(item, item.getOrderItemId()))) {
                throw new BusinessException("订单明细退款确认失败");
            }
        }

        Integer normalCount = orderItemMapper.countNormalByOrderId(order.getOrderId());
        // 状态机 CAS：按剩余正常项数选择 FULL/PARTIAL_REFUND，前置态限定 PAID/SHIPPED/PARTIALLY_REFUNDED，
        // 0 行说明并发退款已推进过聚合状态——幂等跳过，不再盲目覆写。
        OrderStateEvent aggregateEvent = normalCount == null || normalCount == 0
                ? OrderStateEvent.FULL_REFUND : OrderStateEvent.PARTIAL_REFUND;
        if (orderStateMachine.transition(order.getOrderId(),
                Set.of(OrderStatusEnum.PAID, OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED),
                aggregateEvent, order) == 0) {
            log.info("退款聚合状态已被并发推进 orderId={}，跳过", order.getOrderId());
        }
    }

    private static void validateRefundable(OrderInfo order, OrderItem item) {
        Integer status = order.getOrderStatus();
        if (!OrderStatusEnum.PAID.getStatus().equals(status)
                && !OrderStatusEnum.SHIPPED.getStatus().equals(status)
                && !OrderStatusEnum.PARTIALLY_REFUNDED.getStatus().equals(status)) {
            throw new BusinessException("当前订单状态不能申请退款");
        }
        if (!OrderItemStatusEnum.NORMAL.getStatus().equals(item.getOrderItemStatus())) {
            throw new BusinessException("当前订单项状态不能申请退款");
        }
        BigDecimal remaining = item.getRemainingRefundableAmount();
        if (remaining == null || item.getPaidAmount().signum() < 0 || remaining.signum() < 0
                || (item.getRefundedAmount() != null && item.getRefundedAmount().signum() < 0)) {
            throw new BusinessException("订单明细缺少有效实付记录");
        }
        if (item.getBuyCount() == null || item.getBuyCount() <= 0) {
            throw new BusinessException("退款商品数量异常");
        }
        if (order.getPayOrderId() == null || order.getPayOrderId().isBlank()) {
            throw new BusinessException("支付流水不存在");
        }
    }

    private static String stableRefundId(String orderItemId) {
        return UUID.nameUUIDFromBytes(
                ("refund:" + orderItemId).getBytes(StandardCharsets.UTF_8))
                .toString()
                .replace("-", "");
    }

    private static void assertOwner(RefundRequest request, String userId) {
        if (!userId.equals(request.getUserId())) {
            throw new BusinessException("退款请求不存在");
        }
    }

    private static String truncate(String error) {
        if (error == null) {
            return null;
        }
        return error.length() > 500 ? error.substring(0, 500) : error;
    }
}
