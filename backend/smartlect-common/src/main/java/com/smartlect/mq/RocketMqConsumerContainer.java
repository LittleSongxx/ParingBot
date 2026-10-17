package com.smartlect.mq;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.component.MqConsumerIdempotencyHelper;
import com.smartlect.component.MqConsumeFailureRecorder;
import com.smartlect.component.MqListenerHelper;
import jakarta.annotation.PreDestroy;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;
import org.apache.rocketmq.client.apis.consumer.FilterExpression;
import org.apache.rocketmq.client.apis.consumer.FilterExpressionType;
import org.apache.rocketmq.client.apis.consumer.PushConsumer;
import org.apache.rocketmq.client.apis.message.MessageView;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 消费容器：为每个 {@link SmartlectMessageListener} 建 PushConsumer，并统一执行
 * 消费骨架——幂等租约（COMPLETED 跳过 / BUSY 定时延后）→ JSON 反序列化 → 业务
 * 回调 → 完成标记；业务异常进入 {@link MqListenerHelper#handleFailure} 的
 * 5s/30s/120s 定时回投链，耗尽落审查表并归档统一失败 Topic。
 *
 * <p>失败已被妥善调度（回投/归档成功）即向 broker 返回 SUCCESS（消息不再重投，
 * 由我们自己的回投链管理重试节奏）；调度本身失败才返回 FAILURE 由 broker 兜底。
 * 原 RabbitMQ 版 27 个 .retry.N 派生队列由该机制整体取代。</p>
 */
@Slf4j
@Component
public class RocketMqConsumerContainer implements SmartInitializingSingleton {

    @Resource
    private RocketMqClientHolder rocketMqClientHolder;
    @Resource
    private MqConsumerIdempotencyHelper mqConsumerIdempotencyHelper;
    @Resource
    private MqListenerHelper mqListenerHelper;
    @Resource
    private MqConsumeFailureRecorder mqConsumeFailureRecorder;
    @Resource
    private ObjectMapper objectMapper;

    private final List<PushConsumer> consumers = new ArrayList<>();

    @Override
    public void afterSingletonsInstantiated() {
        startAll();
    }

    @Resource
    private org.springframework.context.ApplicationContext applicationContext;

    void startAll() {
        if (applicationContext == null) {
            return;
        }
        var listeners = applicationContext.getBeansOfType(SmartlectMessageListener.class);
        ClientServiceProvider provider = ClientServiceProvider.loadService();
        ClientConfiguration configuration = rocketMqClientHolder.configuration();
        listeners.values().forEach(raw -> {
            @SuppressWarnings("unchecked")
            SmartlectMessageListener<Object> listener =
                    (SmartlectMessageListener<Object>) raw;
            MqSubscription subscription = listener.subscription();
            try {
                FilterExpression filter = new FilterExpression(
                        subscription.tag() == null ? "*" : subscription.tag(),
                        FilterExpressionType.TAG);
                PushConsumer consumer = provider.newPushConsumerBuilder()
                        .setClientConfiguration(configuration)
                        .setConsumerGroup(subscription.consumerGroup())
                        .setSubscriptionExpressions(Map.of(subscription.topic(), filter))
                        .setMessageListener(messageView -> dispatch(listener, messageView))
                        .build();
                consumers.add(consumer);
                log.info("RocketMQ 消费者已启动 topic={}, tag={}, group={}",
                        subscription.topic(), subscription.tag(), subscription.consumerGroup());
            } catch (Exception e) {
                throw new IllegalStateException("RocketMQ 消费者启动失败 " + subscription, e);
            }
        });
    }

    ConsumeResult dispatch(SmartlectMessageListener<Object> listener, MessageView view) {
        SmartlectMqMessage message = wrap(view);
        // 链路追踪贯穿（ADR-0009）：消费线程此前无 MDC，日志与 HTTP/Dubbo 链路无法串联
        String priorTraceId = org.slf4j.MDC.get(com.smartlect.constants.InternalApiHeaders.TRACE_ID_MDC);
        String messageTraceId = message.properties() == null ? null : message.properties().get("traceId");
        if (messageTraceId != null && !messageTraceId.isEmpty()) {
            org.slf4j.MDC.put(com.smartlect.constants.InternalApiHeaders.TRACE_ID_MDC, messageTraceId);
        }
        try {
            return dispatchInTraceContext(listener, message);
        } finally {
            if (messageTraceId != null && !messageTraceId.isEmpty()) {
                if (priorTraceId != null) {
                    org.slf4j.MDC.put(com.smartlect.constants.InternalApiHeaders.TRACE_ID_MDC, priorTraceId);
                } else {
                    org.slf4j.MDC.remove(com.smartlect.constants.InternalApiHeaders.TRACE_ID_MDC);
                }
            }
        }
    }

    private ConsumeResult dispatchInTraceContext(SmartlectMessageListener<Object> listener, SmartlectMqMessage message) {
        long ttl = listener.idempotencyTtlSeconds();
        if (ttl > 0) {
            MqConsumerIdempotencyHelper.ClaimResult claim =
                    mqConsumerIdempotencyHelper.claim(message, ttl);
            if (claim == MqConsumerIdempotencyHelper.ClaimResult.COMPLETED) {
                return ConsumeResult.SUCCESS;
            }
            if (claim == MqConsumerIdempotencyHelper.ClaimResult.BUSY) {
                return mqListenerHelper.deferBusy(message)
                        ? ConsumeResult.SUCCESS : ConsumeResult.FAILURE;
            }
        }
        Object payload;
        try {
            payload = deserialize(message, listener.payloadType());
        } catch (Exception e) {
            // 消息体不可解析：重投无意义，直接归档审查表
            log.error("MQ 消息反序列化失败，归档审查表 queue={}", message.logicalQueue(), e);
            mqConsumeFailureRecorder.record(message.logicalQueue(), message,
                    new String(message.body(), StandardCharsets.UTF_8), e);
            return ConsumeResult.SUCCESS;
        }
        try {
            listener.onMessage(payload, message);
            if (ttl > 0) {
                mqConsumerIdempotencyHelper.markCompleted(message, ttl);
            }
            return ConsumeResult.SUCCESS;
        } catch (Exception e) {
            log.error("MQ 消费失败 queue={}, key={}", message.logicalQueue(),
                    message.idempotencyKey(), e);
            return mqListenerHelper.handleFailure(message, payload, e)
                    ? ConsumeResult.SUCCESS : ConsumeResult.FAILURE;
        }
    }

    private Object deserialize(SmartlectMqMessage message, Class<?> type) throws Exception {
        if (type == String.class) {
            return new String(message.body(), StandardCharsets.UTF_8);
        }
        if (type == byte[].class) {
            return message.body();
        }
        return objectMapper.readValue(message.body(), type);
    }

    static SmartlectMqMessage wrap(MessageView view) {
        String tag = view.getTag().orElse(null);
        ByteBuffer buffer = view.getBody();
        byte[] body = new byte[buffer.remaining()];
        buffer.get(body);
        return SmartlectMqMessage.of(view.getTopic(), tag, body,
                view.getMessageId().toString(), view.getProperties());
    }

    @PreDestroy
    public void shutdown() {
        for (PushConsumer consumer : consumers) {
            try {
                consumer.close();
            } catch (IOException e) {
                log.warn("RocketMQ 消费者关闭异常", e);
            }
        }
    }
}
