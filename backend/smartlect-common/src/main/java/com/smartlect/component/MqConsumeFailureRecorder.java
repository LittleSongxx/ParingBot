package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.entity.dto.MqCompensationRecord;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.service.MqCompensationLogService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 消费最终失败落审查表：exchange 字段写标记值 {@link Constants#MQ_CONSUME_FAILURE_EXCHANGE}
 * （沿用原字段语义），routingKey 写逻辑队列名（topic:tag；存量记录为旧 RabbitMQ
 * 队列名，重放路由两者都可解析）。
 */
@Slf4j
@Component
public class MqConsumeFailureRecorder {

    @Resource
    private MqCompensationStore mqCompensationStore;
    @Resource
    private MqCompensationLogService mqCompensationLogService;

    public void record(String logicalQueue, SmartlectMqMessage message, Object payload, Exception error) {
        if (StringTools.isEmpty(logicalQueue)) {
            return;
        }
        String msgKey = message == null ? null : message.idempotencyKey();
        if (StringTools.isEmpty(msgKey)) {
            msgKey = message == null ? String.valueOf(System.currentTimeMillis()) : message.messageId();
        }
        MqCompensationRecord record = new MqCompensationRecord();
        record.setExchange(Constants.MQ_CONSUME_FAILURE_EXCHANGE);
        record.setRoutingKey(logicalQueue);
        record.setIdempotencyKey("consume:" + logicalQueue + ":" + msgKey);
        record.setPayload(payload);
        record.setReliabilityLevel(MessageReliabilityLevelEnum.STANDARD);
        record.setFailedAt(System.currentTimeMillis());
        record.setErrorMessage(error == null ? "consume failed" : error.getMessage());
        try {
            mqCompensationLogService.saveFromFailure(record);
            mqCompensationStore.saveToRedis(record);
        } catch (Exception e) {
            log.error("MQ 消费失败审查表写入异常 queue={}, key={}", logicalQueue, record.getIdempotencyKey(), e);
            return;
        }
        log.error("MQ 消费最终失败已写入审查表 queue={}, key={}", logicalQueue, record.getIdempotencyKey());
    }
}
