package com.smartlect.constants;

import com.smartlect.component.MqCompensationStore;
import com.smartlect.entity.dto.MqCompensationRecord;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.mq.RocketMqClientHolder;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.service.MqCompensationLogService;
import com.smartlect.utils.StringTools;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

/**
 * 可靠发送：RocketMQ 5.x gRPC 同步 send 返回即 broker 确认（替代原
 * RabbitMQ publisher-confirm 等待）。
 *
 * <p>语义与原版一致：HIGH 级别异步线程池发送（失败落补偿），STANDARD 同步
 * 重试 3 次（1s/2s 间隔）后抛出；replaySend 供 Outbox/补偿重放，幂等由
 * DB 租约与消费侧保证，不查 Redis 发送闸。形参名沿用 outbox 表字段
 * exchange/routingKey，语义为 topic/tag。</p>
 */
@Slf4j
@Component
public class ReliableMessageSender {

    private static final int RETRY_MAX_COUNT = 3;

    @Resource
    private RocketMqClientHolder rocketMqClientHolder;
    @Resource
    private MqCompensationStore mqCompensationStore;
    @Resource
    private MqCompensationLogService mqCompensationLogService;
    @Resource
    private ObjectMapper objectMapper;
    @Resource
    @Qualifier("mqAsyncExecutor")
    private Executor mqAsyncExecutor;

    /** 立即投递。 */
    public void sendMessage(String exchange, String routingKey, Object message,
                            String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel) {
        sendMessage(exchange, routingKey, message, idempotencyKey, reliabilityLevel, null);
    }

    /**
     * 定时投递：deliveryDelay 非空时为定时消息（任意精度，取代原 TTL+死信延迟队列）。
     */
    public void sendMessage(String exchange, String routingKey, Object message,
                            String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel,
                            Duration deliveryDelay) {
        if (StringTools.isEmpty(idempotencyKey)) {
            throw new IllegalArgumentException("MQ 发送必须指定 idempotencyKey");
        }
        if (reliabilityLevel == MessageReliabilityLevelEnum.HIGH) {
            sendHighConcurrency(exchange, routingKey, message, idempotencyKey, deliveryDelay);
        } else {
            sendStandardInternal(exchange, routingKey, message, idempotencyKey, deliveryDelay);
        }
    }

    public void replaySend(String exchange, String routingKey, Object message, String idempotencyKey) {
        replaySend(exchange, routingKey, message, idempotencyKey, null);
    }

    /** 定时重放：Outbox 补发时按剩余延迟投递。 */
    public void replaySend(String exchange, String routingKey, Object message,
                           String idempotencyKey, Duration deliveryDelay) {
        if (StringTools.isEmpty(idempotencyKey)) {
            throw new IllegalArgumentException("MQ 重放必须指定 idempotencyKey");
        }
        // The outbox database lease owns replay idempotency. Redis send guards may outlive
        // a crashed publisher, so consulting them here can turn an unsent row into false SENT.
        sendStandardInternal(exchange, routingKey, message, idempotencyKey, deliveryDelay);
    }

    private void sendHighConcurrency(String topic, String tag, Object message,
                                     String idempotencyKey, Duration deliveryDelay) {
        try {
            mqAsyncExecutor.execute(() -> {
                try {
                    doSend(topic, tag, message, idempotencyKey, deliveryDelay);
                    log.debug("高并发 MQ 已异步发送, topic={}, tag={}, key={}", topic, tag, idempotencyKey);
                } catch (Exception e) {
                    log.error("高并发 MQ 异步发送失败，写入补偿, topic={}, tag={}, key={}",
                            topic, tag, idempotencyKey, e);
                    saveCompensation(topic, tag, message, idempotencyKey, e);
                }
            });
        } catch (RejectedExecutionException e) {
            log.error("高并发 MQ 线程池已满，提交被拒绝，写入补偿, topic={}, tag={}, key={}",
                    topic, tag, idempotencyKey, e);
            saveCompensation(topic, tag, message, idempotencyKey, e);
        }
    }

    private void sendStandardInternal(String topic, String tag, Object message,
                                      String idempotencyKey, Duration deliveryDelay) {
        Exception last = null;
        for (int i = 0; i < RETRY_MAX_COUNT; i++) {
            try {
                if (i > 0) {
                    Thread.sleep(1000L * i);
                }
                doSend(topic, tag, message, idempotencyKey, deliveryDelay);
                log.info("MQ 同步发送成功, topic={}, tag={}, key={}, retry={}",
                        topic, tag, idempotencyKey, i);
                return;
            } catch (Exception e) {
                last = e;
                log.warn("MQ 同步发送失败, key={}, retry={}/{}", idempotencyKey, i + 1, RETRY_MAX_COUNT, e);
            }
        }
        log.error("MQ 同步发送重试耗尽, key={}", idempotencyKey, last);
        throw new IllegalStateException("消息发送失败，已重试 " + RETRY_MAX_COUNT + " 次", last);
    }

    private void doSend(String topic, String tag, Object message,
                        String idempotencyKey, Duration deliveryDelay) throws Exception {
        byte[] body = message instanceof byte[] bytes
                ? bytes : objectMapper.writeValueAsBytes(message);
        rocketMqClientHolder.send(topic, tag, body,
                Map.of(SmartlectMqMessage.PROPERTY_IDEMPOTENCY_KEY, idempotencyKey),
                deliveryDelay);
    }

    private void saveCompensation(String topic, String tag, Object message,
                                  String idempotencyKey, Exception error) {
        MqCompensationRecord record = new MqCompensationRecord();
        record.setIdempotencyKey(idempotencyKey);
        record.setExchange(topic);
        record.setRoutingKey(tag);
        record.setPayload(message);
        record.setReliabilityLevel(MessageReliabilityLevelEnum.HIGH);
        record.setFailedAt(System.currentTimeMillis());
        record.setRetryCount(0);
        record.setErrorMessage(error == null ? null : error.getMessage());
        try {
            mqCompensationLogService.saveFromFailure(record);
            mqCompensationStore.saveToRedis(record);
        } catch (Exception e) {
            log.error("MQ 补偿记录写入失败, key={}", idempotencyKey, e);
        }
    }
}
