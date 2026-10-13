package com.smartlect.component;

import com.smartlect.mq.RocketMqClientHolder;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMqMessage;
import org.apache.rocketmq.client.apis.message.MessageId;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Duration;
import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MqListenerHelperTest {

    @Mock
    private MqConsumerIdempotencyHelper idempotencyHelper;
    @Mock
    private MqConsumeFailureRecorder failureRecorder;
    @Mock
    private RocketMqClientHolder rocketMqClientHolder;
    @Mock
    private MessageId messageId;
    @InjectMocks
    private MqListenerHelper helper;

    @Test
    void failedConsumePublishesDelayedRetryBackToOriginalTopic() throws Exception {
        SmartlectMqMessage source = message(0);
        when(rocketMqClientHolder.send(anyString(), anyString(), any(), any(), any()))
                .thenReturn(messageId);

        assertTrue(helper.handleFailure(source, "payload", new IllegalStateException("temporary")));

        verify(rocketMqClientHolder).send(
                eq(RocketMqTopics.TOPIC_REFUND), eq(RocketMqTopics.TAG_REFUND_STOCK),
                any(), any(), eq(Duration.ofMillis(RocketMqTopics.RETRY_DELAYS_MS[0])));
        ArgumentCaptor<java.util.Map<String, String>> properties =
                ArgumentCaptor.forClass(java.util.Map.class);
        verify(rocketMqClientHolder).send(anyString(), anyString(), any(), properties.capture(), any());
        assertEquals("1", properties.getValue().get(SmartlectMqMessage.PROPERTY_RETRY_ATTEMPT));
        verify(idempotencyHelper).release(source);
        verify(failureRecorder, never()).record(anyString(), any(), any(), any());
    }

    @Test
    void busyClaimDefersWithThirtySeconds() throws Exception {
        SmartlectMqMessage source = message(0);
        when(rocketMqClientHolder.send(anyString(), anyString(), any(), any(), any()))
                .thenReturn(messageId);

        assertTrue(helper.deferBusy(source));

        verify(rocketMqClientHolder).send(
                eq(RocketMqTopics.TOPIC_REFUND), eq(RocketMqTopics.TAG_REFUND_STOCK),
                any(), any(), eq(Duration.ofMillis(RocketMqTopics.BUSY_DEFER_MS)));
    }

    @Test
    void exhaustedRetriesFallBackToReviewLedgerAndFailureTopic() throws Exception {
        SmartlectMqMessage source = message(RocketMqTopics.DEFAULT_MAX_CONSUME_RETRIES);
        when(rocketMqClientHolder.send(anyString(), anyString(), any(), any(), any()))
                .thenReturn(messageId);

        assertTrue(helper.handleFailure(source, "payload", new IllegalStateException("permanent")));

        // 不再回投原 Topic，只归档统一失败 Topic
        verify(rocketMqClientHolder).send(
                eq(RocketMqTopics.TOPIC_MQ_FAILURE), eq(source.logicalQueue()),
                any(), any(), isNull());
        verify(failureRecorder).record(eq(source.logicalQueue()), eq(source), any(), any());
    }

    @Test
    void retryPublishFailureReturnsFalseForBrokerRedelivery() throws Exception {
        SmartlectMqMessage source = message(0);
        when(rocketMqClientHolder.send(anyString(), anyString(), any(), any(), any()))
                .thenThrow(new IllegalStateException("broker down"));

        assertFalse(helper.handleFailure(source, "payload", new IllegalStateException("temporary")));

        verify(failureRecorder).record(eq(source.logicalQueue()), eq(source), any(), any());
    }

    private static SmartlectMqMessage message(int retryAttempt) {
        HashMap<String, String> properties = new HashMap<>();
        properties.put(SmartlectMqMessage.PROPERTY_IDEMPOTENCY_KEY, "message-1");
        if (retryAttempt > 0) {
            properties.put(SmartlectMqMessage.PROPERTY_RETRY_ATTEMPT, String.valueOf(retryAttempt));
        }
        return SmartlectMqMessage.of(
                RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_STOCK,
                new byte[0], "msg-1", properties);
    }
}
