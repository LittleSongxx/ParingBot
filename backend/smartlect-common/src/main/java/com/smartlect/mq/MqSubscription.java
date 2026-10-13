package com.smartlect.mq;

/**
 * 消费订阅声明。consumerGroup 跨实例同名（负载均衡），按业务域命名
 * G_smartlect_{域}（如 G_smartlect_refund_stock）。
 */
public record MqSubscription(String topic, String tag, String consumerGroup) {

    /** tag 为 null 表示订阅该 Topic 全部 Tag（Canal CDC 场景）。 */
    public static MqSubscription of(String topic, String tag, String consumerGroup) {
        return new MqSubscription(topic, tag, consumerGroup);
    }

    public String logicalQueue() {
        return RocketMqTopics.logicalQueue(topic, tag == null ? "*" : tag);
    }
}
