package com.smartlect.task;

import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.mappers.OrderRequestIdempotencyMapper;
import com.smartlect.metrics.SmartlectMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 对账哨兵：只上报、不改判——这是幂等账本能守住"不确定 ≠ 失败"的关键约束。 */
class OrderIdempotencyReconcileTaskTest {

    private final OrderRequestIdempotencyMapper mapper = mock(OrderRequestIdempotencyMapper.class);
    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

    private OrderIdempotencyReconcileTask task() {
        OrderIdempotencyReconcileTask task = new OrderIdempotencyReconcileTask();
        ReflectionTestUtils.setField(task, "orderRequestIdempotencyMapper", mapper);
        ReflectionTestUtils.setField(task, "metrics", new SmartlectMetrics(registry));
        ReflectionTestUtils.setField(task, "batchSize", 50);
        return task;
    }

    private OrderRequestIdempotency row(String status, String key) {
        OrderRequestIdempotency row = new OrderRequestIdempotency();
        row.setStatus(status);
        row.setCommandType("COMMERCE_CANCEL_ORDER");
        row.setIdempotencyKey(key);
        row.setReconcileAttempts(3);
        row.setReconcileDeadline(new Date());
        row.setReviewReason("processing_stale");
        return row;
    }

    @Test
    void reportsStuckLedgerRowsAsMetricWithoutMutatingThem() {
        when(mapper.selectStuckForReview(anyInt())).thenReturn(List.of(
                row("INCONCLUSIVE", "key-inconclusive"), row("MANUAL_REVIEW", "key-manual")));

        task().reconcile();

        assertEquals(1.0, registry.get("smartlect_idempotent_stuck_total")
                .tag("status", "INCONCLUSIVE").counter().count());
        assertEquals(1.0, registry.get("smartlect_idempotent_stuck_total")
                .tag("status", "MANUAL_REVIEW").counter().count());
        // 任务不得写账本：改判只能由带业务参数的核对（CommerceActionStatusService）来做
        verify(mapper, never()).markCompleted(org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any());
        verify(mapper, never()).markFailed(org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any());
    }

    @Test
    void emptyScanIsANoOp() {
        when(mapper.selectStuckForReview(anyInt())).thenReturn(List.of());

        task().reconcile();

        assertNull(registry.find("smartlect_idempotent_stuck_total").counter(),
                "没有待核对行时不应新增指标");
    }
}
