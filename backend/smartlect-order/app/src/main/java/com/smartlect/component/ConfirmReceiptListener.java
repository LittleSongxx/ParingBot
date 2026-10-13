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
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 自动确认收货：发货后经 Outbox 投递的定时消息（7 天）到期触发。
 * 确认收货需要事务——通过自身代理调用 @Transactional 方法，返回即事务已提交，
 * 容器随后写入消费完成标记（等价于原「事务提交后 ack」语义）。
 */
@Slf4j
@Component
public class ConfirmReceiptListener implements SmartlectMessageListener<PayOrderMessageDTO> {

    /** 自注入走代理，让 @Transactional 生效（自调用不走代理 = 没有事务）。 */
    @Lazy
    @Resource
    private ConfirmReceiptListener self;

    @Resource
    private OrderInfoService orderInfoService;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_CONFIRM_RECEIPT,
                "G_smartlect_confirm_receipt");
    }

    @Override
    public Class<PayOrderMessageDTO> payloadType() {
        return PayOrderMessageDTO.class;
    }

    @Override
    public void onMessage(PayOrderMessageDTO message, SmartlectMqMessage mqMessage) {
        if (message == null || StringTools.isEmpty(message.getOrderId())) {
            log.error("确认收货消息订单为空");
            return;
        }
        log.info("确认收货消息收到订单: {}", message.getOrderId());
        self.processOrderConfirm(message);
    }

    @Transactional(rollbackFor = Exception.class)
    public void processOrderConfirm(PayOrderMessageDTO message) {
        orderInfoService.confirmOrderReceipt(null, message.getOrderId());
    }
}
