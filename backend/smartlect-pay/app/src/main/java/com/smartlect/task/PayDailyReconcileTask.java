package com.smartlect.task;

import com.smartlect.metrics.SmartlectMetrics;
import com.xxl.job.core.handler.annotation.XxlJob;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

/**
 * Mock 渠道日对账（ADR-0009）：支付意图/退款表 vs 渠道事件流水。
 *
 * <p>只报告差异，不自动改账。差异可能是上线前未回填的历史行、写入中断，
 * 或有人绕开渠道接口直接改库；每一种都要人看一眼再决定补流水还是修业务状态。
 * 定时任务默认每天 03:10 由 xxl-job 触发。</p>
 */
@Component
@Slf4j
public class PayDailyReconcileTask {

    private static final String COMPLETE_CONDITION =
            "pay_channel = 'mock' and trade_status in (1, 3)";

    @Resource
    private JdbcTemplate jdbc;

    @Resource
    private SmartlectMetrics metrics;

    @XxlJob("payDailyReconcile")
    public void reconcile() {
        long completedIntents = count("select count(*) from pay_trade_record where " + COMPLETE_CONDITION);
        long completeEvents = count(
                "select count(*) from pay_mock_channel_ledger where event_type = 'COMPLETE' and status = 'SUCCESS'");
        BigDecimal paidAmount = amount(
                "select coalesce(sum(pay_amount), 0) from pay_trade_record where " + COMPLETE_CONDITION);
        BigDecimal completeLedgerAmount = amount(
                "select coalesce(sum(amount), 0) from pay_mock_channel_ledger "
                        + "where event_type = 'COMPLETE' and status = 'SUCCESS'");

        long refunds = count("select count(*) from pay_mock_refund");
        long refundEvents = count(
                "select count(*) from pay_mock_channel_ledger where event_type = 'REFUND' and status = 'SUCCESS'");
        BigDecimal refundAmount = amount("select coalesce(sum(refund_amount), 0) from pay_mock_refund");
        BigDecimal refundLedgerAmount = amount(
                "select coalesce(sum(amount), 0) from pay_mock_channel_ledger "
                        + "where event_type = 'REFUND' and status = 'SUCCESS'");

        report("complete_missing", Math.max(0, completedIntents - completeEvents));
        report("complete_orphan", Math.max(0, completeEvents - completedIntents));
        report("refund_missing", Math.max(0, refunds - refundEvents));
        report("refund_orphan", Math.max(0, refundEvents - refunds));
        if (paidAmount.compareTo(completeLedgerAmount) != 0) {
            metrics.payReconcileDiff("complete_amount", 1);
            log.warn("Mock 支付对账金额差异：业务表实付合计={}，渠道流水合计={}",
                    paidAmount, completeLedgerAmount);
        }
        if (refundAmount.compareTo(refundLedgerAmount) != 0) {
            metrics.payReconcileDiff("refund_amount", 1);
            log.warn("Mock 退款对账金额差异：退款表合计={}，渠道流水合计={}",
                    refundAmount, refundLedgerAmount);
        }
        log.info("Mock 支付日对账完成：支付意图/流水={}/{}, 退款/流水={}/{}, 实付={}/{}, 退款={}/{}",
                completedIntents, completeEvents, refunds, refundEvents,
                paidAmount, completeLedgerAmount, refundAmount, refundLedgerAmount);
    }

    private void report(String type, long diff) {
        if (diff > 0) {
            metrics.payReconcileDiff(type, diff);
            log.warn("Mock 支付对账差异 {}={}", type, diff);
        }
    }

    private long count(String sql) {
        Long value = jdbc.queryForObject(sql, Long.class);
        return value == null ? 0 : value;
    }

    private BigDecimal amount(String sql) {
        BigDecimal value = jdbc.queryForObject(sql, BigDecimal.class);
        return value == null ? BigDecimal.ZERO : value;
    }
}
