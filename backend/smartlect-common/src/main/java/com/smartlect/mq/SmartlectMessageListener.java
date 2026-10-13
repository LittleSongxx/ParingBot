package com.smartlect.mq;

/**
 * 业务监听器契约：实现类声明订阅与载荷类型，消费骨架（幂等租约、失败重试、
 * 审查表归档）由 RocketMqConsumerContainer 统一执行。
 *
 * <p>监听器只写业务逻辑——原 RabbitMQ 消费者里的 tryBeginConsume/ack/nack 骨架
 * 全部上收容器模板；需要事务的方法自行加 @Transactional（返回即事务提交后）。</p>
 *
 * @param <T> 消息载荷类型（JSON 反序列化目标）
 */
public interface SmartlectMessageListener<T> {

    /** 订阅声明：topic、tag、消费组。 */
    MqSubscription subscription();

    /** 载荷类型，容器按此反序列化 body。 */
    Class<T> payloadType();

    /**
     * 处理消息。抛出异常即进入容器统一的重试链（定时回投 5s/30s/120s，
     * 耗尽落 mq_compensation_log 审查表并归档统一失败 Topic）。
     */
    void onMessage(T payload, SmartlectMqMessage message) throws Exception;

    /**
     * 消费幂等 TTL（秒）。默认 24 小时；资金/退款类覆盖为 7 天。
     * 返回 0 表示跳过幂等租约（如 Canal CDC 的幂等 upsert 消费者）。
     */
    default long idempotencyTtlSeconds() {
        return 24 * 3600L;
    }
}
