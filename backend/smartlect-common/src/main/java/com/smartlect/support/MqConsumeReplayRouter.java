package com.smartlect.support;

import com.smartlect.constants.Constants;
import com.smartlect.mq.RocketMqTopics;

/**
 * 消费失败重放路由：routing_key 存两种形态——新记录为逻辑队列名（topic:tag），
 * 存量 RabbitMQ 记录为旧队列名；两者都解析到新 (topic, tag)。
 */
public final class MqConsumeReplayRouter {

    private MqConsumeReplayRouter() {
    }

    public record Target(String exchange, String routingKey) {
    }

    public static Target resolve(String routingKey) {
        if (routingKey == null) {
            return null;
        }
        // 新形态：topic:tag
        int separator = routingKey.lastIndexOf(':');
        if (separator > 0 && !routingKey.startsWith("smartlect.")) {
            String topic = routingKey.substring(0, separator);
            String tag = routingKey.substring(separator + 1);
            if (!topic.isEmpty() && !tag.isEmpty()) {
                return new Target(topic, tag);
            }
        }
        // 存量形态：旧 RabbitMQ 队列名
        RocketMqTopics.Target legacy = RocketMqTopics.resolveByLegacyQueue(routingKey);
        return legacy == null ? null : new Target(legacy.topic(), legacy.tag());
    }

    public static boolean isConsumeFailure(String exchange) {
        return Constants.MQ_CONSUME_FAILURE_EXCHANGE.equals(exchange);
    }
}
