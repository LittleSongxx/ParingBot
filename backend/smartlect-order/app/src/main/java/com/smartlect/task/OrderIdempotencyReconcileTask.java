package com.smartlect.task;

import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.mappers.OrderRequestIdempotencyMapper;
import com.smartlect.metrics.SmartlectMetrics;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import com.xxl.job.core.handler.annotation.XxlJob;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 幂等账本的对账哨兵：把"核对中/待人工"的行暴露出来，不让它们静默腐烂。
 *
 * <p><b>为什么只上报不改判</b>：账本只存 userId + commandType + 幂等键，<b>不存业务参数</b>
 * （订单号、券号等），因此服务端无法独自证明"原请求到底成交没有"。真正的出口是既有能力
 * ——调用方带着业务参数走 {@code /internal/order/commerce/actionStatus} 复核
 * （{@code CommerceActionStatusService} 会去业务表看效果是否已发生，发生则 markReconciled、
 * 未发生则累计核对次数直至人工）。本任务负责"发现"，运维脚本负责"驱动出口"：
 * {@code scripts/reconcile_idempotency.py}。擅自把 UNKNOWN 猜成 FAILED 会让"没成交"与
 * "成交了但响应丢了"再也分不开——这是幂等账本最不能做的事。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(
        name = "order.idempotency.reconcile-report-enabled",
        havingValue = "true",
        matchIfMissing = true)
public class OrderIdempotencyReconcileTask {

    @Resource
    private OrderRequestIdempotencyMapper orderRequestIdempotencyMapper;
    @Resource
    private SmartlectMetrics metrics;

    @Value("${order.idempotency.reconcile-batch-size:50}")
    private int batchSize;

    @XxlJob("orderIdempotencyReconcile")
    public void reconcile() {
        int boundedBatch = Math.max(1, Math.min(batchSize, 500));
        List<OrderRequestIdempotency> stuck =
                orderRequestIdempotencyMapper.selectStuckForReview(boundedBatch);
        if (stuck == null || stuck.isEmpty()) {
            return;
        }
        for (OrderRequestIdempotency row : stuck) {
            metrics.idempotentStuck(row.getStatus());
            log.warn("幂等账本待核对：status={} command={} key={} attempts={} deadline={} reason={} "
                            + "—— 用 scripts/reconcile_idempotency.py 带业务参数驱动出口",
                    row.getStatus(), row.getCommandType(), row.getIdempotencyKey(),
                    row.getReconcileAttempts(), row.getReconcileDeadline(), row.getReviewReason());
        }
        log.warn("本轮发现 {} 条待核对幂等记录（见上；不自动改判，避免把 UNKNOWN 猜成结果）", stuck.size());
    }
}
