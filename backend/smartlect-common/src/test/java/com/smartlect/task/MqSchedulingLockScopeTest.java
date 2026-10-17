package com.smartlect.task;

import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.service.MqCompensationLogService;
import com.smartlect.service.OutboxMessageService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.concurrent.TimeUnit;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class MqSchedulingLockScopeTest {

    private RedisComponent redisComponent;

    @BeforeEach
    void setUp() {
        redisComponent = mock(RedisComponent.class);
    }

    @Test
    void outboxLockIsScopedToTheOwningServiceDatabase() {
        OutboxMessageService service = mock(OutboxMessageService.class);
        OutboxDispatchTask task = new OutboxDispatchTask();
        ReflectionTestUtils.setField(task, "redisComponent", redisComponent);
        ReflectionTestUtils.setField(task, "outboxMessageService", service);
        ReflectionTestUtils.setField(task, "batchSize", 10);
        ReflectionTestUtils.setField(task, "maxRetries", 10);
        ReflectionTestUtils.setField(task, "applicationName", "smartlect-product");
        String expectedKey = Constants.REDIS_KEY_MQ_COMPENSATE
                + "outbox:dispatch:lock:smartlect-product";
        when(redisComponent.setIfAbsent(eq(expectedKey), eq("1"), anyLong(), eq(TimeUnit.SECONDS)))
                .thenReturn(true);

        task.dispatch();

        verify(service).dispatchPendingBatch(10, 10);
    }

    @Test
    void compensationLockIsScopedToTheOwningServiceDatabase() {
        MqCompensationLogService service = mock(MqCompensationLogService.class);
        MqCompensationAutoReplayTask task = new MqCompensationAutoReplayTask();
        ReflectionTestUtils.setField(task, "redisComponent", redisComponent);
        ReflectionTestUtils.setField(task, "mqCompensationLogService", service);
        ReflectionTestUtils.setField(task, "batchSize", 10);
        ReflectionTestUtils.setField(task, "maxRetries", 5);
        ReflectionTestUtils.setField(task, "includeConsumeFailures", false);
        ReflectionTestUtils.setField(task, "applicationName", "smartlect-user");
        String expectedKey = Constants.REDIS_KEY_MQ_COMPENSATE_AUTO_REPLAY_LOCK
                + ":smartlect-user";
        when(redisComponent.setIfAbsent(expectedKey, "1", 55, TimeUnit.SECONDS))
                .thenReturn(true);

        task.autoReplay();

        verify(service).autoReplayPendingSendFailures(10, 5, false);
    }
}
