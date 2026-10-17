package com.smartlect.api.dto;

/**
 * 退款全额还券事件（ADR-0006）：order 侧 Saga 收尾在短事务内经 Outbox 发出，
 * coupon 侧消费做幂等还券（USED→NOUSE，券过期则跳过）。
 */
public class RefundCouponReturnDTO {

    private String orderId;
    private String payOrderId;
    private String userCouponId;
    private String couponId;

    public RefundCouponReturnDTO() {
    }

    public RefundCouponReturnDTO(String orderId, String payOrderId, String userCouponId, String couponId) {
        this.orderId = orderId;
        this.payOrderId = payOrderId;
        this.userCouponId = userCouponId;
        this.couponId = couponId;
    }

    public String getOrderId() {
        return orderId;
    }

    public void setOrderId(String orderId) {
        this.orderId = orderId;
    }

    public String getPayOrderId() {
        return payOrderId;
    }

    public void setPayOrderId(String payOrderId) {
        this.payOrderId = payOrderId;
    }

    public String getUserCouponId() {
        return userCouponId;
    }

    public void setUserCouponId(String userCouponId) {
        this.userCouponId = userCouponId;
    }

    public String getCouponId() {
        return couponId;
    }

    public void setCouponId(String couponId) {
        this.couponId = couponId;
    }
}
