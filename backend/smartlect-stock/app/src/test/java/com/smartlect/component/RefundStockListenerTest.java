package com.smartlect.component;

import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.biz.SkuStockService;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.constants.ReliableMessageSender;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

class RefundStockListenerTest {

    private final SkuStockService skuStockService = mock(SkuStockService.class);
    private final ReliableMessageSender reliableMessageSender = mock(ReliableMessageSender.class);
    private RefundStockListener listener;

    @BeforeEach
    void setUp() {
        listener = new RefundStockListener();
        ReflectionTestUtils.setField(listener, "skuStockService", skuStockService);
        ReflectionTestUtils.setField(listener, "reliableMessageSender", reliableMessageSender);
    }

    @Test
    void successfulRestorePublishesIdempotentResult() {
        RefundStockRestoreDTO payload = payload();
        SmartlectMqMessage message = message();

        listener.onMessage(payload, message);

        verify(skuStockService).restoreRefundStock(payload);
        verify(reliableMessageSender).replaySend(
                eq(RocketMqTopics.TOPIC_REFUND),
                eq(RocketMqTopics.TAG_REFUND_RESULT),
                any(),
                eq("refund:result:r1"));
    }

    @Test
    void incompletePayloadIsRejectedForContainerRetry() {
        assertThrows(IllegalArgumentException.class,
                () -> listener.onMessage(new RefundStockRestoreDTO(), message()));
        verify(skuStockService, never()).restoreRefundStock(any());
    }

    @Test
    void restoreFailurePropagatesForContainerRetryChain() {
        RefundStockRestoreDTO payload = payload();
        doThrow(new IllegalStateException("db unavailable"))
                .when(skuStockService).restoreRefundStock(payload);

        assertThrows(IllegalStateException.class, () -> listener.onMessage(payload, message()));
        verify(reliableMessageSender, never()).replaySend(any(), any(), any(), any());
    }

    @Test
    void subscriptionAndTtlMatchRefundSemantics() {
        assertEquals(RocketMqTopics.TOPIC_REFUND, listener.subscription().topic());
        assertEquals(RocketMqTopics.TAG_REFUND_STOCK, listener.subscription().tag());
        assertEquals(7 * 24 * 3600L, listener.idempotencyTtlSeconds());
        assertEquals(RefundStockRestoreDTO.class, listener.payloadType());
    }

    private static RefundStockRestoreDTO payload() {
        RefundStockRestoreDTO payload = new RefundStockRestoreDTO();
        payload.setRefundRequestId("r1");
        payload.setBusinessKey("refund:r1");
        payload.setProductId("p1");
        payload.setPropertyValueIdHash("sku1");
        payload.setChangeAmount(2);
        return payload;
    }

    private static SmartlectMqMessage message() {
        return SmartlectMqMessage.of(RocketMqTopics.TOPIC_REFUND, RocketMqTopics.TAG_REFUND_STOCK,
                new byte[0], "msg-1", new HashMap<>());
    }
}
