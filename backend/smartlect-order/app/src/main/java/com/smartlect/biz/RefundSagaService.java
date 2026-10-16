package com.smartlect.biz;

import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.entity.enums.RefundSagaStatus;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.exception.BusinessException;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import com.xxl.job.core.handler.annotation.XxlJob;
import org.springframework.stereotype.Service;

import java.util.List;

@Slf4j
@Service
public class RefundSagaService {

    @Resource
    private RefundSagaTransactionService transactionService;
    @Resource
    private PayRpcSupport payRpcSupport;
    @Resource
    private StockRpcSupport stockRpcSupport;

    public void requestRefund(OrderItem item, String userId) {
        if (item == null || item.getOrderItemId() == null) {
            throw new BusinessException("订单项不存在");
        }
        RefundRequest request = transactionService.createOrLoad(item.getOrderItemId(), userId);
        if (RefundSagaStatus.MANUAL_REVIEW.name().equals(request.getStatus())) {
            throw new BusinessException("退款正在人工复核，请勿重复提交");
        }
        if (RefundSagaStatus.REJECTED.name().equals(request.getStatus())) {
            // 驳回 = 本次申请作废；用户重新发起即重开新申请，重新走全流程。
            transactionService.resetRejected(request.getRefundRequestId());
        }
        processPayment(request, true);
    }

    public void requestConfirmedRefund(String orderItemId, String userId, long amountCents) {
        RefundRequest request = transactionService.createOrLoadConfirmed(orderItemId, userId, amountCents);
        if (RefundSagaStatus.REJECTED.name().equals(request.getStatus())
                || RefundSagaStatus.MANUAL_REVIEW.name().equals(request.getStatus())) {
            throw new BusinessException("退款需重新核验或人工处理");
        }
        processPayment(request, true);
    }

    @XxlJob("refundSagaReconcile")
    public void reconcile() {
        List<RefundRequest> due = transactionService.selectDue(30);
        for (RefundRequest request : due) {
            try {
                RefundSagaStatus status = RefundSagaStatus.valueOf(request.getStatus());
                if (status == RefundSagaStatus.PENDING_PAYMENT) {
                    processPayment(request, false);
                } else if (status == RefundSagaStatus.PAYMENT_CONFIRMED) {
                    transactionService.queueStockRestore(request.getRefundRequestId(), false);
                } else if (status == RefundSagaStatus.STOCK_PENDING) {
                    reconcileStock(request);
                }
            } catch (Exception e) {
                log.warn("退款 Saga 对账失败, refundRequestId={}",
                        request.getRefundRequestId(), e);
            }
        }
    }

    private void processPayment(RefundRequest request, boolean userRequest) {
        RefundRequest current = transactionService.get(request.getRefundRequestId());
        if (current == null) {
            throw new BusinessException("退款请求不存在");
        }
        RefundSagaStatus status = RefundSagaStatus.valueOf(current.getStatus());
        if (status == RefundSagaStatus.COMPLETED || status == RefundSagaStatus.STOCK_PENDING) {
            return;
        }
        if (status == RefundSagaStatus.PAYMENT_CONFIRMED) {
            transactionService.queueStockRestore(current.getRefundRequestId(), false);
            return;
        }
        if (!transactionService.claimPaymentAttempt(current.getRefundRequestId())) {
            return;
        }

        try {
            PayChannelEnum channel = PayChannelEnum.resolve(current.getPayChannel());
            payRpcSupport.refund(
                    current.getSourcePayOrderId(),
                    current.getRefundOrderNo(),
                    current.getRefundAmount(),
                    channel == null ? null : channel.getPayScene());
            transactionService.markPaymentConfirmed(current.getRefundRequestId());
            transactionService.queueStockRestore(current.getRefundRequestId(), false);
        } catch (Exception e) {
            transactionService.recordPaymentFailure(current.getRefundRequestId(), e.getMessage());
            if (userRequest) {
                throw new BusinessException("退款请求已记录，支付渠道暂时异常，系统将自动重试");
            }
            throw e;
        }
    }

    private void reconcileStock(RefundRequest request) {
        if (stockRpcSupport.isRefundStockApplied(request.getRefundRequestId())) {
            transactionService.markCompleted(request.getRefundRequestId());
            return;
        }
        transactionService.queueStockRestore(request.getRefundRequestId(), true);
    }
}
