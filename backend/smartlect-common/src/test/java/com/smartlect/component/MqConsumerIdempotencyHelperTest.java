package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMqMessage;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MqConsumerIdempotencyHelperTest {

    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;

    private MqConsumerIdempotencyHelper helper;

    @BeforeEach
    void setUp() {
        helper = new MqConsumerIdempotencyHelper();
        ReflectionTestUtils.setField(helper, "stringRedisTemplate", redisTemplate);
        ReflectionTestUtils.setField(helper, "processingLeaseSeconds", 300L);
        lenient().when(redisTemplate.opsForValue()).thenReturn(valueOperations);
    }

    @Test
    void acquiredLeaseCarriesOwnerTokenAndReleaseUsesAtomicScript() {
        SmartlectMqMessage message = message("queue-a", "message-1");
        when(redisTemplate.hasKey(any())).thenReturn(false);
        when(valueOperations.setIfAbsent(any(), any(), anyLong(), eq(TimeUnit.SECONDS)))
                .thenReturn(true);

        assertEquals(MqConsumerIdempotencyHelper.ClaimResult.ACQUIRED, helper.claim(message, 3_600L));
        String token = message.property(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN);
        assertNotNull(token);

        helper.release(message);

        assertNull(message.property(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN));
        verify(redisTemplate).execute(any(), any(), eq(token));
    }

    @Test
    void completionWithoutLeaseStillWritesQueueScopedDoneMarker() {
        SmartlectMqMessage message = message("queue-b", "message-2");

        helper.markCompleted(message, 10L);

        verify(valueOperations).set(
                eq(Constants.REDIS_KEY_MQ_CONSUME_IDEMPOTENT + "done:"
                        + message.logicalQueue() + ":message-2"),
                eq("1"),
                eq(60L),
                eq(TimeUnit.SECONDS));
    }

    @Test
    void completionScriptChecksLeaseBeforeWritingDoneMarker() {
        DefaultRedisScript<?> script = (DefaultRedisScript<?>) ReflectionTestUtils.getField(
                MqConsumerIdempotencyHelper.class, "COMPLETE_LEASE_SCRIPT");
        assertNotNull(script);
        String source = script.getScriptAsString();

        int ownershipCheck = source.indexOf("if current ~= ARGV[1] then return 0 end");
        int doneWrite = source.indexOf("redis.call('SET', KEYS[2]");
        assertTrue(ownershipCheck >= 0);
        assertTrue(doneWrite > ownershipCheck);
        assertFalse(source.substring(0, ownershipCheck).contains("KEYS[2]"));
    }

    @Test
    void duplicateMessageDoesNotStealAnActiveProcessingLease() {
        SmartlectMqMessage message = message("queue-c", "message-3");
        when(redisTemplate.hasKey(any())).thenReturn(false);
        when(valueOperations.setIfAbsent(any(), any(), anyLong(), eq(TimeUnit.SECONDS)))
                .thenReturn(false);

        assertEquals(MqConsumerIdempotencyHelper.ClaimResult.BUSY, helper.claim(message, 3_600L));
        assertNull(message.property(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN));
    }

    @Test
    void completedDuplicateIsDistinctFromAnActiveLease() {
        SmartlectMqMessage message = message("queue-e", "message-5");
        when(redisTemplate.hasKey(any())).thenReturn(true);

        assertEquals(MqConsumerIdempotencyHelper.ClaimResult.COMPLETED, helper.claim(message, 3_600L));
    }

    @Test
    void redisClaimFailureDefersMessageInsteadOfEscapingTheListener() {
        SmartlectMqMessage message = message("queue-f", "message-6");
        when(redisTemplate.hasKey(any()))
                .thenThrow(new IllegalStateException("redis unavailable"));

        assertEquals(MqConsumerIdempotencyHelper.ClaimResult.BUSY, helper.claim(message, 3_600L));
    }

    @Test
    void redisReleaseFailureDoesNotBlockRetryPublishing() {
        SmartlectMqMessage message = message("queue-g", "message-7");
        message.withProperty(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN, "lease-7");
        doThrow(new IllegalStateException("redis unavailable"))
                .when(redisTemplate)
                .execute(any(), any(), eq("lease-7"));

        helper.release(message);

        assertNull(message.property(MqConsumerIdempotencyHelper.PROPERTY_CONSUMER_LEASE_TOKEN));
    }

    private static SmartlectMqMessage message(String logicalQueue, String idempotencyKey) {
        String[] parts = logicalQueue.split(":", 2);
        SmartlectMqMessage message = SmartlectMqMessage.of(
                parts.length == 2 ? parts[0] : RocketMqTopics.TOPIC_PAY,
                parts.length == 2 ? parts[1] : logicalQueue,
                new byte[0], "msg-id-" + idempotencyKey, new HashMap<>());
        message.withProperty(SmartlectMqMessage.PROPERTY_IDEMPOTENCY_KEY, idempotencyKey);
        return message;
    }
}
