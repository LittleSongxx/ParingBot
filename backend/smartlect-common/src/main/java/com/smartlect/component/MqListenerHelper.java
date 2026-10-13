package com.smartlect.component;

import com.smartlect.mq.RocketMqClientHolder;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMqMessage;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 消费失败调度：重试链（定时回投原 Topic/Tag，间隔 5s/30s/120s，对齐原三级 TTL
 * 拓扑）与最终失败归档（mq_compensation_log 审查表 + 统一失败 Topic）。
 *
 * <p>返回 true 表示失败已被妥善调度（回投或归档成功），容器据此向 broker 返回
 * SUCCESS；false 表示调度本身失败，容器返回 FAILURE 交由 broker 重投兜底。</p>
 */
@Slf4j
@Component
public class MqListenerHelper {

    private static final int MAX_RETRIES = RocketMqTopics.DEFAULT_MAX_CONSUME_RETRIES;

    @Resource
    private RocketMqClientHolder rocketMqClientHolder;
    @Resource
    private MqConsumerIdempotencyHelper mqConsumerIdempotencyHelper;
    @Resource
    private MqConsumeFailureRecorder mqConsumeFailureRecorder;

    /** 幂等租约被占用（BUSY）：30s 后回投原 Topic/Tag 重试。 */
    public boolean deferBusy(SmartlectMqMessage message) {
        String queue = message.logicalQueue();
        String key = message.idempotencyKey();
        try {
            redeliver(message, Duration.ofMillis(RocketMqTopics.BUSY_DEFER_MS),
                    "busy:" + queue + ":" + key + ":" + UUID.randomUUID());
            log.debug("MQ 消费租约占用，消息已延后重试 queue={}, key={}", queue, key);
            return true;
        } catch (Exception publishError) {
            log.error("MQ 消费租约占用消息延后失败 queue={}, key={}", queue, key, publishError);
            return false;
        }
    }

    /**
     * 业务失败：attempt ≤ MAX_RETRIES 时按 5s/30s/120s 定时回投；耗尽则落审查表
     * 并归档统一失败 Topic。
     */
    public boolean handleFailure(SmartlectMqMessage message, Object payload, Exception error) {
        String queue = message.logicalQueue();
        String key = message.idempotencyKey();
        mqConsumerIdempotencyHelper.release(message);
        int attempt = message.retryAttempt() + 1;
        if (attempt <= MAX_RETRIES) {
            long delay = RocketMqTopics.RETRY_DELAYS_MS[attempt - 1];
            log.warn("MQ 消费失败进入延迟重试 queue={}, key={}, attempt={}/{}",
                    queue, key, attempt, MAX_RETRIES);
            try {
                redeliverWithAttempt(message, attempt, Duration.ofMillis(delay),
                        "retry:" + queue + ":" + key + ":" + attempt);
                return true;
            } catch (Exception publishError) {
                log.error("MQ 延迟重试消息发布失败 queue={}, key={}", queue, key, publishError);
                mqConsumeFailureRecorder.record(queue, message, payload, publishError);
                return publishFailure(message, "failed:" + queue + ":" + key + ":" + UUID.randomUUID());
            }
        }
        mqConsumeFailureRecorder.record(queue, message, payload, error);
        return publishFailure(message, "failed:" + queue + ":" + key + ":" + UUID.randomUUID());
    }

    /** 归档到统一失败 Topic（无消费者，DB 审查表为准）。 */
    private boolean publishFailure(SmartlectMqMessage message, String correlationId) {
        try {
            Map<String, String> properties = new HashMap<>(message.properties());
            properties.put(SmartlectMqMessage.PROPERTY_IDEMPOTENCY_KEY, correlationId);
            properties.remove(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN);
            properties.remove(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_CLAIM_RESULT);
            rocketMqClientHolder.send(RocketMqTopics.TOPIC_MQ_FAILURE,
                    message.logicalQueue(), message.body(), properties, null);
            return true;
        } catch (Exception publishError) {
            log.error("MQ 最终失败消息归档发布失败 queue={}, correlationId={}",
                    message.logicalQueue(), correlationId, publishError);
            return false;
        }
    }

    private void redeliver(SmartlectMqMessage message, Duration delay, String idempotencyKey)
            throws Exception {
        redeliverInternal(message, message.retryAttempt(), delay, idempotencyKey);
    }

    private void redeliverWithAttempt(SmartlectMqMessage message, int attempt,
                                      Duration delay, String idempotencyKey) throws Exception {
        redeliverInternal(message, attempt, delay, idempotencyKey);
    }

    private void redeliverInternal(SmartlectMqMessage message, int attempt,
                                   Duration delay, String idempotencyKey) throws Exception {
        Map<String, String> properties = new HashMap<>(message.properties());
        properties.put(SmartlectMqMessage.PROPERTY_RETRY_ATTEMPT, String.valueOf(attempt));
        // 回投是新的投递：幂等键保持业务键不变（Redis done/processing 按业务键去重），
        // 租约相关 property 只存在于内存，不进入重发消息。
        properties.remove(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN);
        properties.remove(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_CLAIM_RESULT);
        rocketMqClientHolder.send(message.topic(), message.tag(), message.body(), properties, delay);
    }
}
