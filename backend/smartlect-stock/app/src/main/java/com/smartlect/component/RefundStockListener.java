package com.smartlect.component;

import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.dto.RefundStockResultDTO;
import com.smartlect.biz.SkuStockService;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.support.MqIdempotencyKeys;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 退款 Saga 的库存恢复步：按 refundRequestId 幂等回补库存，成功后回发退款结果。
 * 消费骨架（幂等租约/重试链）由容器统一执行；TTL 7 天（资金相关）。
 */
@Slf4j
@Component
public class RefundStockListener implements SmartlectMessageListener<RefundStockRestoreDTO> {

    @Resource
    private SkuStockService skuStockService;
    @Resource
    private ReliableMessageSender reliableMessageSender;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_STOCK,
                "G_smartlect_refund_stock");
    }

    @Override
    public Class<RefundStockRestoreDTO> payloadType() {
        return RefundStockRestoreDTO.class;
    }

    @Override
    public long idempotencyTtlSeconds() {
        return 7 * 24 * 3600L;
    }

    @Override
    public void onMessage(RefundStockRestoreDTO payload, SmartlectMqMessage message) {
        if (payload == null || payload.getRefundRequestId() == null) {
            throw new IllegalArgumentException("退款库存恢复消息字段不完整");
        }
        skuStockService.restoreRefundStock(payload);
        RefundStockResultDTO result = new RefundStockResultDTO(
                payload.getRefundRequestId(), payload.getBusinessKey());
        reliableMessageSender.replaySend(
                RocketMqTopics.TOPIC_REFUND,
                RocketMqTopics.TAG_REFUND_RESULT,
                result,
                MqIdempotencyKeys.refundResult(payload.getRefundRequestId()));
    }
}
