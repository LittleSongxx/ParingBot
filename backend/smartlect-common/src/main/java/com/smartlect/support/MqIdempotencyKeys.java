package com.smartlect.support;

import com.smartlect.utils.StringTools;

public final class MqIdempotencyKeys {

    private MqIdempotencyKeys() {
    }

    public static String paySuccess(String payOrderId) {
        return "pay-success:" + payOrderId;
    }

    public static String payTimeout(String orderId) {
        return "pay:timeout:" + require(orderId);
    }

    public static String payLogistics(String orderId) {
        return payLogistics(orderId, 0);
    }

    public static String payLogistics(String orderId, int step) {
        return "pay:logistics:" + require(orderId) + ":step:" + step;
    }

    public static String payConfirm(String orderId) {
        return "pay:confirm:" + require(orderId);
    }

    /**
     * 退款回补库存的事件幂等键。
     *
     * <p>`attempt` 之外再带一个"轮次标识"（调用方传该行进入本轮时的 updated_at 毫秒 epoch）：
     * 人工审批/驳回会把 retry_count 归零（recordPaymentFailure→reviewApprove/resetRejected），
     * 只按 retry_count 组键会让新一轮生成与旧一轮相同的键，命中 Outbox"同键同载荷直接返回"
     * → **审批通过实际什么都没重发**，退款静静卡在 STOCK_PENDING（2026-10-16 审计 M4）。
     * 轮次标识变化即生成新事件；库存侧按 refundRequestId 幂等，重复送达安全。</p>
     */
    public static String refundStock(String refundRequestId, int attempt, long episodeEpochMs) {
        return "refund:stock:" + require(refundRequestId) + ":attempt:" + attempt
                + ":ep" + episodeEpochMs;
    }

    public static String refundResult(String refundRequestId) {
        return "refund:result:" + require(refundRequestId);
    }

    public static String orderGrowth(String orderId) {
        return "order:growth:" + require(orderId);
    }

    public static String browseRecord(String userId, String productId, long browseTime) {
        if (browseTime <= 0) {
            throw new IllegalArgumentException("浏览事件时间必须为正数");
        }
        return "browse:" + require(userId) + ":" + require(productId) + ":at:" + browseTime;
    }

    public static String signRecord(String userId, String yyyyMMdd) {
        return "sign:record:" + require(userId) + ":" + require(yyyyMMdd);
    }

    public static String notification(String userId, String bizType, String bizId) {
        return "notify:" + require(userId) + ":"
                + (bizType == null ? "" : bizType) + ":"
                + (bizId == null ? "" : bizId);
    }

    public static String tempBanUnban(String userId, long unbanAtMs) {
        return "tempban:unban:" + require(userId) + ":" + unbanAtMs;
    }

    private static String require(String value) {
        if (StringTools.isEmpty(value)) {
            throw new IllegalArgumentException("MQ 幂等键参数不能为空");
        }
        return value;
    }
}
