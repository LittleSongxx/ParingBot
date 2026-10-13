package com.smartlect.mq;

import java.util.HashMap;
import java.util.Map;

/**
 * 中间件中立的消息模型：消费侧从 RocketMQ MessageView 包装，发送侧（回投/延后/失败
 * 归档）以此重建 Message。幂等键与重试计数走消息 property，替代原 AMQP header。
 */
public final class SmartlectMqMessage {

    /** 与原 AMQP header 同名，消费幂等键约定。 */
    public static final String PROPERTY_IDEMPOTENCY_KEY = "x-idempotency-key";
    /** 消费重试计数（第 N 次重投），替代原 x-smartlect-retry-attempt。 */
    public static final String PROPERTY_RETRY_ATTEMPT = "x-smartlect-retry-attempt";

    private final String topic;
    private final String tag;
    private final byte[] body;
    private final String messageId;
    private final Map<String, String> properties;

    private SmartlectMqMessage(String topic, String tag, byte[] body,
                               String messageId, Map<String, String> properties) {
        this.topic = topic;
        this.tag = tag;
        this.body = body;
        this.messageId = messageId;
        this.properties = properties;
    }

    public static SmartlectMqMessage of(String topic, String tag, byte[] body,
                                        String messageId, Map<String, String> properties) {
        return new SmartlectMqMessage(topic, tag, body, messageId,
                properties == null ? new HashMap<>() : new HashMap<>(properties));
    }

    public String topic() {
        return topic;
    }

    public String tag() {
        return tag;
    }

    public byte[] body() {
        return body;
    }

    public String messageId() {
        return messageId;
    }

    public Map<String, String> properties() {
        return properties;
    }

    public String property(String key) {
        return properties.get(key);
    }

    public SmartlectMqMessage withProperty(String key, String value) {
        properties.put(key, value);
        return this;
    }

    /** 逻辑队列名：消费幂等 Redis 键按 topic:tag 隔离。 */
    public String logicalQueue() {
        return RocketMqTopics.logicalQueue(topic, tag);
    }

    /** 消费重试计数（0 表示首次投递）。 */
    public int retryAttempt() {
        String value = property(PROPERTY_RETRY_ATTEMPT);
        if (value == null) {
            return 0;
        }
        try {
            return Integer.parseInt(value);
        } catch (NumberFormatException ignored) {
            return 0;
        }
    }

    /** 幂等键：property 优先，回退 messageId。 */
    public String idempotencyKey() {
        String value = property(PROPERTY_IDEMPOTENCY_KEY);
        return (value == null || value.isEmpty()) ? messageId : value;
    }
}
