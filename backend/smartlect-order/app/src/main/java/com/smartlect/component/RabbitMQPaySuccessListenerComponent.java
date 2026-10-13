package com.smartlect.component;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.biz.OrderInternalService;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.utils.StringTools;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 消费 pay 服务发来的支付成功事件（Outbox → smartlect-pay/pay-success）。
 *
 * <p>取代 pay→order 的同步 Feign 回调。paySuccess 的推进本身是条件更新
 * （仅待付款订单可迁移），事件重投或 outbox 重放天然幂等，再叠加消费租约
 * 去重与定时回投重试链。</p>
 */
@Slf4j
@Component
public class RabbitMQPaySuccessListenerComponent implements SmartlectMessageListener<PayOrderNotifyDTO> {

    private final OrderInternalService orderInternalService;

    public RabbitMQPaySuccessListenerComponent(OrderInternalService orderInternalService) {
        this.orderInternalService = orderInternalService;
    }

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_PAY, RocketMqTopics.TAG_PAY_SUCCESS,
                "G_smartlect_pay_success");
    }

    @Override
    public Class<PayOrderNotifyDTO> payloadType() {
        return PayOrderNotifyDTO.class;
    }

    @Override
    public long idempotencyTtlSeconds() {
        return 7 * 24 * 3600L;
    }

    @Override
    public void onMessage(PayOrderNotifyDTO message, SmartlectMqMessage mqMessage) {
        if (message == null || StringTools.isEmpty(message.getPayOrderId())) {
            log.error("支付成功事件缺少支付单号");
            return;
        }
        log.info("支付成功事件收到 payOrderId={}", message.getPayOrderId());
        orderInternalService.paySuccess(message);
    }
}
