package com.smartlect.mq;

import java.time.Duration;
import java.util.List;
import java.util.Set;

/**
 * RocketMQ 拓扑：Topic/Tag 常量、历史队列名映射与延迟语义。
 *
 * <p>迁移自 RabbitMQ 的 6 交换机/18 队列模型（2026-10-13，ADR-0016）：
 * Direct 交换机 + routingKey 收敛为 Topic + Tag；5 组 TTL+死信延迟队列收敛为
 * 发送侧定时消息（任意精度，RocketMQ 5.x）；27 个 .retry.N 派生队列由
 * 消费失败时的定时回投取代（间隔 5s/30s/120s，见 {@link #RETRY_DELAYS_MS}）。
 * mq_compensation_log / local_message_outbox 表的 exchange/routing_key 字段名
 * 不变，语义演化为 topic/tag。</p>
 */
public final class RocketMqTopics {

    private RocketMqTopics() {
    }

    /** 支付域事件：支付成功、超时关单、物流推进、自动收货。 */
    public static final String TOPIC_PAY = "smartlect-pay";
    /** 退款 Saga：库存恢复与完成回执。 */
    public static final String TOPIC_REFUND = "smartlect-refund";
    /** 秒杀：下单队列清退与超时死信。 */
    public static final String TOPIC_RUSH = "smartlect-rush";
    /** Canal CDC（canal.serverMode=rocketMQ 直投，flatMessage JSON）。 */
    public static final String TOPIC_CANAL = "smartlect-canal";
    /**
     * 定时消息专用 Topic（message.type=DELAY）：5.x 对 DELAY 类型消息按 Topic
     * 属性校验，且属性值含逗号（NORMAL,DELAY）无法经 mqadmin CLI 表达，故
     * 定时与即时消息分流到不同 Topic，Tag 语义保持不变。
     */
    public static final String TOPIC_DELAY = "smartlect-delay";
    /** 消费最终失败的统一归档 Topic（无消费者，DB 补偿表为准）。 */
    public static final String TOPIC_MQ_FAILURE = "smartlect-mq-failure";

    public static final String TAG_PAY_SUCCESS = "pay-success";
    public static final String TAG_PAY_TIMEOUT_CLOSE = "pay-timeout-close";
    public static final String TAG_LOGISTICS_STEP = "logistics-step";
    public static final String TAG_CONFIRM_RECEIPT = "confirm-receipt";
    public static final String TAG_REFUND_STOCK = "refund-stock";
    public static final String TAG_REFUND_RESULT = "refund-result";
    public static final String TAG_RUSH_ORDER = "rush-order";
    public static final String TAG_RUSH_TIMEOUT = "rush-timeout";
    public static final String TAG_TEMPBAN_EXPIRE = "tempban-expire";

    /** 消费失败重试间隔（毫秒）：第 1/2/3 次，对齐原 RabbitMQ 三级 TTL 拓扑。 */
    public static final long[] RETRY_DELAYS_MS = {5_000L, 30_000L, 120_000L};

    /** BUSY（幂等租约占用）延后间隔，对齐原 .retry.2 队列的 30s。 */
    public static final long BUSY_DEFER_MS = 30_000L;

    public static final int DEFAULT_MAX_CONSUME_RETRIES = 3;

    /** Producer 需要预声明的全部业务 Topic。 */
    public static final List<String> ALL_PUBLISH_TOPICS = List.of(
            TOPIC_PAY, TOPIC_REFUND, TOPIC_RUSH, TOPIC_DELAY, TOPIC_MQ_FAILURE);

    /**
     * 历史 RabbitMQ 队列名 → (topic, tag) 映射：mq_compensation_log 存量记录的
     * routing_key 仍是旧队列名，人工/自动重放按此路由到新拓扑。
     */
    public static Target resolveByLegacyQueue(String queueName) {
        if (queueName == null) {
            return null;
        }
        return switch (queueName) {
            case "smartlect.pay.success.queue" -> new Target(TOPIC_PAY, TAG_PAY_SUCCESS);
            case "smartlect.pay.timeout.dead.queue" -> new Target(TOPIC_DELAY, TAG_PAY_TIMEOUT_CLOSE);
            case "smartlect.pay.logistics.dead.queue" -> new Target(TOPIC_DELAY, TAG_LOGISTICS_STEP);
            case "smartlect.pay.confirm.dead.queue" -> new Target(TOPIC_DELAY, TAG_CONFIRM_RECEIPT);
            case "smartlect.refund.stock.queue", "smartlect.refund.stock.dead.queue"
                    -> new Target(TOPIC_REFUND, TAG_REFUND_STOCK);
            case "smartlect.refund.result.queue", "smartlect.refund.result.dead.queue"
                    -> new Target(TOPIC_REFUND, TAG_REFUND_RESULT);
            case "smartlect.rushing.order.queue" -> new Target(TOPIC_RUSH, TAG_RUSH_ORDER);
            case "smartlect.rushing.dead.queue" -> new Target(TOPIC_DELAY, TAG_RUSH_TIMEOUT);
            case "smartlect.user.tempban.dead.queue" -> new Target(TOPIC_DELAY, TAG_TEMPBAN_EXPIRE);
            default -> null;
        };
    }

    /** 延迟语义常量：与原 @Value 默认值一致，供发送点引用。 */
    public static final Duration PAY_TIMEOUT = Duration.ofMinutes(15);
    public static final Duration RUSH_EXPIRE = Duration.ofMinutes(15);
    public static final Duration LOGISTICS_STEP = Duration.ofHours(1);
    public static final Duration CONFIRM_RECEIPT = Duration.ofDays(7);
    public static final Duration TEMP_BAN = Duration.ofHours(2);

    public record Target(String topic, String tag) {
    }

    /** 消费幂等 Redis 键沿用的逻辑队列名（按 topic:tag 派生，与旧队列名解耦）。 */
    public static String logicalQueue(String topic, String tag) {
        return topic + ":" + tag;
    }

    /** 全部可消费 (topic, tag)——用于自检订阅声明。 */
    public static Set<String> allLogicalQueues() {
        return Set.of(
                logicalQueue(TOPIC_PAY, TAG_PAY_SUCCESS),
                logicalQueue(TOPIC_DELAY, TAG_PAY_TIMEOUT_CLOSE),
                logicalQueue(TOPIC_DELAY, TAG_LOGISTICS_STEP),
                logicalQueue(TOPIC_DELAY, TAG_CONFIRM_RECEIPT),
                logicalQueue(TOPIC_REFUND, TAG_REFUND_STOCK),
                logicalQueue(TOPIC_REFUND, TAG_REFUND_RESULT),
                logicalQueue(TOPIC_RUSH, TAG_RUSH_ORDER),
                logicalQueue(TOPIC_DELAY, TAG_RUSH_TIMEOUT),
                logicalQueue(TOPIC_DELAY, TAG_TEMPBAN_EXPIRE));
    }
}
