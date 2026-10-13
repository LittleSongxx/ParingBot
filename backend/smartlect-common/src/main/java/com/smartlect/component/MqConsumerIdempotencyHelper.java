package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/**
 * 消费幂等：Redis 三态租约（processing 租约 + done 标记 + Lua 原子完成）。
 * 机制与 RabbitMQ 版完全一致，仅消息载体换成 {@link SmartlectMqMessage}
 * （租约 token 经内存 property 传递，不再写回 broker）。
 */
@Slf4j
@Component
public class MqConsumerIdempotencyHelper {

    public static final String PROPERTY_CONSUMER_LEASE_TOKEN = "x-smartlect-consumer-lease-token";
    public static final String PROPERTY_CONSUMER_CLAIM_RESULT = "x-smartlect-consumer-claim-result";

    public enum ClaimResult {
        ACQUIRED,
        COMPLETED,
        BUSY
    }

    private static final DefaultRedisScript<Long> RELEASE_LEASE_SCRIPT = new DefaultRedisScript<>(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                    + "return redis.call('DEL', KEYS[1]) "
                    + "else return 0 end",
            Long.class);

    private static final DefaultRedisScript<Long> COMPLETE_LEASE_SCRIPT = new DefaultRedisScript<>(
            "local current = redis.call('GET', KEYS[1]); "
                    + "if current ~= ARGV[1] then return 0 end; "
                    + "redis.call('SET', KEYS[2], '1', 'EX', ARGV[2]); "
                    + "redis.call('DEL', KEYS[1]); "
                    + "return 1",
            Long.class);

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Value("${mq.consume.processing-lease-seconds:300}")
    private long processingLeaseSeconds;

    /**
     * 抢占消费权。COMPLETED：此前已消费完成；BUSY：他实例正在处理或 Redis 不可用
     * （均应由调用方延后/跳过）；ACQUIRED：本实例获得租约，token 写入消息 property。
     */
    public ClaimResult claim(SmartlectMqMessage message, long ttlSeconds) {
        try {
            return claimInternal(message, ttlSeconds);
        } catch (RuntimeException exception) {
            log.error("MQ 消费幂等存储不可用，消息将延后重试, queue={}, key={}",
                    message.logicalQueue(), message.idempotencyKey(), exception);
            return ClaimResult.BUSY;
        }
    }

    private ClaimResult claimInternal(SmartlectMqMessage message, long ttlSeconds) {
        String key = message.idempotencyKey();
        if (StringTools.isEmpty(key)) {
            return ClaimResult.ACQUIRED;
        }
        String queue = message.logicalQueue();
        String doneKey = doneKey(queue, key);
        if (Boolean.TRUE.equals(stringRedisTemplate.hasKey(doneKey))) {
            log.debug("MQ 消费幂等跳过已完成消息, queue={}, key={}", queue, key);
            return ClaimResult.COMPLETED;
        }
        String processingKey = processingKey(queue, key);
        String leaseToken = UUID.randomUUID().toString();
        Boolean acquired = stringRedisTemplate.opsForValue()
                .setIfAbsent(processingKey, leaseToken,
                        Math.max(30L, processingLeaseSeconds), TimeUnit.SECONDS);
        if (!Boolean.TRUE.equals(acquired)) {
            log.debug("MQ 消费租约占用, queue={}, key={}", queue, key);
            return ClaimResult.BUSY;
        }
        message.withProperty(PROPERTY_CONSUMER_LEASE_TOKEN, leaseToken);
        if (Boolean.TRUE.equals(stringRedisTemplate.hasKey(doneKey))) {
            releaseLease(processingKey, leaseToken);
            message.properties().remove(PROPERTY_CONSUMER_LEASE_TOKEN);
            return ClaimResult.COMPLETED;
        }
        return ClaimResult.ACQUIRED;
    }

    /** 释放租约（业务失败将重试时）。 */
    public void release(SmartlectMqMessage message) {
        String key = message.idempotencyKey();
        if (StringTools.isEmpty(key)) {
            return;
        }
        String leaseToken = message.property(PROPERTY_CONSUMER_LEASE_TOKEN);
        if (StringTools.isEmpty(leaseToken)) {
            return;
        }
        try {
            releaseLease(processingKey(message.logicalQueue(), key), leaseToken);
        } catch (RuntimeException exception) {
            log.warn("MQ 消费租约释放失败，将等待租约自然过期, queue={}, key={}",
                    message.logicalQueue(), key, exception);
        } finally {
            message.properties().remove(PROPERTY_CONSUMER_LEASE_TOKEN);
        }
    }

    /** 完成标记：token 匹配时原子地 processing→done（Lua），防并发双完成。 */
    public void markCompleted(SmartlectMqMessage message, long ttlSeconds) {
        String key = message.idempotencyKey();
        if (StringTools.isEmpty(key)) {
            return;
        }
        String queue = message.logicalQueue();
        String doneKey = doneKey(queue, key);
        String processingKey = processingKey(queue, key);
        String leaseToken = message.property(PROPERTY_CONSUMER_LEASE_TOKEN);
        long completedTtl = Math.max(60L, ttlSeconds);
        if (StringTools.isEmpty(leaseToken)) {
            stringRedisTemplate.opsForValue().set(doneKey, "1", completedTtl, TimeUnit.SECONDS);
            return;
        }
        Long completed = stringRedisTemplate.execute(
                COMPLETE_LEASE_SCRIPT,
                List.of(processingKey, doneKey),
                leaseToken,
                String.valueOf(completedTtl));
        if (!Long.valueOf(1L).equals(completed)) {
            log.warn("MQ 消费完成标记被拒绝，处理租约已转移, queue={}, key={}", queue, key);
        }
        message.properties().remove(PROPERTY_CONSUMER_LEASE_TOKEN);
    }

    private void releaseLease(String processingKey, String leaseToken) {
        stringRedisTemplate.execute(RELEASE_LEASE_SCRIPT, List.of(processingKey), leaseToken);
    }

    private String processingKey(String queueName, String key) {
        return Constants.REDIS_KEY_MQ_CONSUME_IDEMPOTENT + "processing:" + queueName + ":" + key;
    }

    private String doneKey(String queueName, String key) {
        return Constants.REDIS_KEY_MQ_CONSUME_IDEMPOTENT + "done:" + queueName + ":" + key;
    }
}
