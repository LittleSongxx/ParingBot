package com.smartlect.biz;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;

/**
 * Mock 渠道事件流水（ADR-0009）。
 *
 * <p>支付意图表记录“应当收多少”，退款表记录“退了哪几笔”，流水账记录“渠道确实确认过什么”。
 * 三者分开后，日对账才能在不信任业务表的前提下发现缺口。事件键由业务键派生，
 * 重复调用由唯一键吸收，因此重放不会产生第二行。</p>
 */
@Service
public class PayMockChannelLedgerService {

    private final JdbcTemplate jdbc;

    public PayMockChannelLedgerService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void recordComplete(String payOrderId, BigDecimal amount) {
        insert("complete:" + payOrderId, "COMPLETE", payOrderId, null, amount);
    }

    public void recordRefund(String refundOrderId, String sourcePayOrderId, BigDecimal amount) {
        insert("refund:" + refundOrderId, "REFUND", sourcePayOrderId, refundOrderId, amount);
    }

    private void insert(String eventId, String eventType, String payOrderId,
                        String refundOrderId, BigDecimal amount) {
        jdbc.update("""
                insert ignore into pay_mock_channel_ledger
                    (event_id, event_type, pay_order_id, refund_order_id, amount, status)
                values (?, ?, ?, ?, ?, 'SUCCESS')
                """, eventId, eventType, payOrderId, refundOrderId, amount);
    }
}
