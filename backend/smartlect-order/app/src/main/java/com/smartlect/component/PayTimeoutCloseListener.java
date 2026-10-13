package com.smartlect.component;

import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 支付超时关单：下单时经 Outbox 投递的定时消息（15 分钟，任意精度）到期触发，
 * 轮询任务兜底。幂等租约防多实例重复关单（关单本身也是状态机条件更新）。
 */
@Slf4j
@Component
public class PayTimeoutCloseListener implements SmartlectMessageListener<PayOrderMessageDTO> {

    @Resource
    private OrderInfoService orderInfoService;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_PAY_TIMEOUT_CLOSE,
                "G_smartlect_pay_timeout_close");
    }

    @Override
    public Class<PayOrderMessageDTO> payloadType() {
        return PayOrderMessageDTO.class;
    }

    @Override
    public void onMessage(PayOrderMessageDTO message, SmartlectMqMessage mqMessage) {
        if (message == null || StringTools.isEmpty(message.getOrderId())) {
            log.error("支付超时关单消息订单为空");
            return;
        }
        log.info("支付超时关单消息收到订单: {}", message.getOrderId());
        if (!orderInfoService.cancelUnpaidOrderForPayTimeout(message.getOrderId())) {
            throw new IllegalStateException("关单未生效，稍后重试 orderId=" + message.getOrderId());
        }
    }
}
