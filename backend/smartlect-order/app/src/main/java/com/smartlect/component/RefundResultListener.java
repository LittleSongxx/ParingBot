package com.smartlect.component;

import com.smartlect.api.dto.RefundStockResultDTO;
import com.smartlect.biz.RefundSagaTransactionService;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 退款 Saga 完成回执：stock 恢复库存后回发，order 据此把 refund_request 推到
 * COMPLETED。TTL 7 天（资金相关）。
 */
@Slf4j
@Component
public class RefundResultListener implements SmartlectMessageListener<RefundStockResultDTO> {

    @Resource
    private RefundSagaTransactionService transactionService;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_RESULT,
                "G_smartlect_refund_result");
    }

    @Override
    public Class<RefundStockResultDTO> payloadType() {
        return RefundStockResultDTO.class;
    }

    @Override
    public long idempotencyTtlSeconds() {
        return 7 * 24 * 3600L;
    }

    @Override
    public void onMessage(RefundStockResultDTO result, SmartlectMqMessage mqMessage) {
        if (result == null || result.getRefundRequestId() == null) {
            throw new IllegalArgumentException("退款结果消息字段不完整");
        }
        transactionService.markCompleted(result.getRefundRequestId());
    }
}
