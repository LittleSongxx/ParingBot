package com.smartlect.service.impl;

import com.github.pagehelper.PageHelper;
import com.smartlect.component.MqCompensationStore;
import com.smartlect.component.MqIdempotencyGuard;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.entity.po.MqCompensationLog;
import com.smartlect.entity.query.MqCompensationLogQuery;
import com.smartlect.mappers.MqCompensationLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 自动重放的取舍：发送失败/远程补偿默认重放；消费失败默认留给人判，
 * 只有显式打开（coupon 的退款还券）才一起重放。
 */
@ExtendWith(MockitoExtension.class)
class MqCompensationLogServiceImplTest {

    @Mock
    private MqCompensationLogMapper<MqCompensationLog, MqCompensationLogQuery> mqCompensationLogMapper;
    @Mock
    private MqIdempotencyGuard mqIdempotencyGuard;
    @Mock
    private MqCompensationStore mqCompensationStore;
    @Mock
    private ReliableMessageSender reliableMessageSender;

    private MqCompensationLogServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new MqCompensationLogServiceImpl();
        ReflectionTestUtils.setField(service, "mqCompensationLogMapper", mqCompensationLogMapper);
        ReflectionTestUtils.setField(service, "mqIdempotencyGuard", mqIdempotencyGuard);
        ReflectionTestUtils.setField(service, "mqCompensationStore", mqCompensationStore);
        ReflectionTestUtils.setField(service, "reliableMessageSender", reliableMessageSender);
    }

    @AfterEach
    void clearPageHelper() {
        PageHelper.clearPage();
    }

    @Test
    void consumeFailuresStayForManualReplayByDefault() {
        when(mqCompensationLogMapper.selectList(any()))
                .thenReturn(List.of(sendFailure(), consumeFailure()));

        int replayed = service.autoReplayPendingSendFailures(10, 5);

        assertEquals(1, replayed);
        verify(reliableMessageSender, times(1))
                .replaySend(eq("smartlect-pay"), eq("pay-success"), any(), eq("send-1"));
        verify(reliableMessageSender, never())
                .replaySend(eq("smartlect-refund"), eq("refund-coupon-return"), any(), any());
    }

    @Test
    void couponConsumeFailureIsReplayedWhenExplicitlyEnabled() {
        when(mqCompensationLogMapper.selectList(any())).thenReturn(List.of(consumeFailure()));

        int replayed = service.autoReplayPendingSendFailures(10, 5, true);

        assertEquals(1, replayed);
        verify(reliableMessageSender)
                .replaySend(eq("smartlect-refund"), eq("refund-coupon-return"), any(), eq("consume-1"));
    }

    @Test
    void rowsExceedingRetryLimitAreSkipped() {
        MqCompensationLog row = sendFailure();
        row.setRetryCount(5);
        when(mqCompensationLogMapper.selectList(any())).thenReturn(List.of(row));

        assertEquals(0, service.autoReplayPendingSendFailures(10, 5));
        verify(reliableMessageSender, never()).replaySend(any(), any(), any(), any());
    }

    private static MqCompensationLog sendFailure() {
        return row("send-1", "smartlect-pay", "pay-success");
    }

    private static MqCompensationLog consumeFailure() {
        return row("consume-1", "mq.consume", "smartlect-refund:refund-coupon-return");
    }

    private static MqCompensationLog row(String idempotencyKey, String exchange, String routingKey) {
        MqCompensationLog row = new MqCompensationLog();
        row.setLogId(1);
        row.setIdempotencyKey(idempotencyKey);
        row.setExchange(exchange);
        row.setRoutingKey(routingKey);
        row.setPayloadJson("{}");
        row.setRetryCount(0);
        return row;
    }
}
