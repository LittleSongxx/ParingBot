package com.smartlect.component;

import com.smartlect.api.dto.RefundCouponReturnDTO;
import com.smartlect.biz.CouponInternalService;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 退款 Saga 的全额还券步（ADR-0006）：消费 order 侧收尾发出的还券事件，
 * USED→NOUSE 条件更新幂等；券过期/状态不符按终态跳过。TTL 7 天（资金相关）。
 */
@Slf4j
@Component
public class RefundCouponReturnListener implements SmartlectMessageListener<RefundCouponReturnDTO> {

    @Resource
    private CouponInternalService couponInternalService;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_COUPON_RETURN,
                "G_smartlect_refund_coupon");
    }

    @Override
    public Class<RefundCouponReturnDTO> payloadType() {
        return RefundCouponReturnDTO.class;
    }

    @Override
    public long idempotencyTtlSeconds() {
        return 7 * 24 * 3600L;
    }

    @Override
    public void onMessage(RefundCouponReturnDTO payload, SmartlectMqMessage message) {
        if (payload == null || payload.getUserCouponId() == null) {
            throw new IllegalArgumentException("退款还券消息字段不完整");
        }
        couponInternalService.returnCouponForRefund(payload);
    }
}
