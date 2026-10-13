package com.smartlect.mq;

import com.smartlect.component.MqConsumerIdempotencyHelper;
import com.smartlect.component.MqConsumeFailureRecorder;
import com.smartlect.component.MqListenerHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.Spy;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 消费容器模板语义：COMPLETED 跳过、BUSY 定时延后、业务异常进入重试链、
 * 反序列化失败直接归档（不重投）、成功路径写完成标记。
 */
@ExtendWith(MockitoExtension.class)
class RocketMqConsumerContainerTest {

    @Mock
    private MqConsumerIdempotencyHelper idempotencyHelper;
    @Mock
    private MqListenerHelper mqListenerHelper;
    @Mock
    private MqConsumeFailureRecorder failureRecorder;
    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();
    @InjectMocks
    private RocketMqConsumerContainer container;

    private TestListener listener;

    @BeforeEach
    void setUp() {
        listener = new TestListener();
    }

    @Test
    void completedClaimSkipsBusinessLogic() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.COMPLETED);

        ConsumeResult result = container.dispatch(listener,
                new FakeView("{\"v\":1}"));

        assertEquals(ConsumeResult.SUCCESS, result);
        assertEquals(0, listener.calls);
    }

    @Test
    void busyClaimDefersAndReportsSuccessWhenDeferred() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.BUSY);
        when(mqListenerHelper.deferBusy(any())).thenReturn(true);

        ConsumeResult result = container.dispatch(listener,
                new FakeView("{\"v\":1}"));

        assertEquals(ConsumeResult.SUCCESS, result);
        assertEquals(0, listener.calls);
    }

    @Test
    void busyClaimReturnsFailureWhenDeferPublishFails() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.BUSY);
        when(mqListenerHelper.deferBusy(any())).thenReturn(false);

        assertEquals(ConsumeResult.FAILURE,
                container.dispatch(listener, new FakeView("{\"v\":1}")));
    }

    @Test
    void businessExceptionEntersRetryChain() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.ACQUIRED);
        when(mqListenerHelper.handleFailure(any(), any(), any())).thenReturn(true);
        listener.failWith = new IllegalStateException("db down");

        assertEquals(ConsumeResult.SUCCESS,
                container.dispatch(listener, new FakeView("{\"v\":1}")));
        verify(mqListenerHelper).handleFailure(any(), any(), any());
        verify(idempotencyHelper, never()).markCompleted(any(), anyLong());
    }

    @Test
    void malformedBodyArchivesWithoutRetry() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.ACQUIRED);

        assertEquals(ConsumeResult.SUCCESS,
                container.dispatch(listener, new FakeView("not-json")));
        verify(failureRecorder).record(anyString(), any(), any(), any());
        assertEquals(0, listener.calls);
    }

    @Test
    void successMarksCompleted() {
        when(idempotencyHelper.claim(any(), anyLong()))
                .thenReturn(MqConsumerIdempotencyHelper.ClaimResult.ACQUIRED);

        assertEquals(ConsumeResult.SUCCESS,
                container.dispatch(listener, new FakeView("{\"v\":1}")));
        verify(idempotencyHelper).markCompleted(any(), anyLong());
    }

    @Test
    void zeroTtlSkipsClaimAndCompletion() {
        listener.ttl = 0;

        assertEquals(ConsumeResult.SUCCESS,
                container.dispatch(listener, new FakeView("{\"v\":1}")));
        verify(idempotencyHelper, never()).claim(any(), anyLong());
        verify(idempotencyHelper, never()).markCompleted(any(), anyLong());
    }

    /** 可控测试监听器：默认成功，可注入失败。 */
    @SuppressWarnings("unchecked")
    static class TestListener implements SmartlectMessageListener<Object> {
        volatile RuntimeException failWith;
        volatile long ttl = 86_400L;
        volatile int calls;

        @Override
        public MqSubscription subscription() {
            return MqSubscription.of("t-test", "tag-a", "G_test");
        }

        @Override
        public Class<Object> payloadType() {
            return (Class<Object>) (Class<?>) Payload.class;
        }

        @Override
        public long idempotencyTtlSeconds() {
            return ttl;
        }

        @Override
        public void onMessage(Object payload, SmartlectMqMessage message) {
            calls++;
            if (failWith != null) {
                throw failWith;
            }
        }
    }

    record Payload(int v) {
    }

    /** 规避对 MessageView 接口 mock 的样板：实现其用到的访问器。 */
    static class FakeView implements org.apache.rocketmq.client.apis.message.MessageView {
        private final String body;

        FakeView(String body) {
            this.body = body;
        }

        @Override
        public org.apache.rocketmq.client.apis.message.MessageId getMessageId() {
            return () -> "test-msg-id";
        }

        @Override
        public String getTopic() {
            return "t-test";
        }

        @Override
        public ByteBuffer getBody() {
            return ByteBuffer.wrap(body.getBytes(StandardCharsets.UTF_8));
        }

        @Override
        public java.util.Map<String, String> getProperties() {
            return new HashMap<>();
        }

        @Override
        public java.util.Optional<String> getTag() {
            return java.util.Optional.of("tag-a");
        }

        @Override
        public java.util.Collection<String> getKeys() {
            return java.util.List.of();
        }

        @Override
        public java.util.Optional<String> getMessageGroup() {
            return java.util.Optional.empty();
        }

        @Override
        public java.util.Optional<Long> getDeliveryTimestamp() {
            return java.util.Optional.empty();
        }

        @Override
        public String getBornHost() {
            return "127.0.0.1";
        }

        @Override
        public long getBornTimestamp() {
            return 0L;
        }


        @Override
        public int getDeliveryAttempt() {
            return 1;
        }
    }
}
