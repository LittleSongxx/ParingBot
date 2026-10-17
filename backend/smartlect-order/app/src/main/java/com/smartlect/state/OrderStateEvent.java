package com.smartlect.state;

/**
 * 订单状态机事件。事件描述“发生了什么”，目标状态由 {@link OrderStateMachine} 的转移表唯一决定，
 * 调用方不得自行计算目标状态。
 */
public enum OrderStateEvent {
    CREATE("创建订单"),
    PAY_SUCCESS("支付成功"),
    COUPON_RUSH_PAY_SUCCESS("秒杀券支付成功"),
    USER_CANCEL("用户取消"),
    SYSTEM_CANCEL("系统取消（无用户上下文的取消路径）"),
    PAYMENT_TIMEOUT("支付超时关单"),
    SHIP("发货"),
    CONFIRM_RECEIPT("确认收货"),
    PARTIAL_REFUND("部分退款"),
    FULL_REFUND("全额退款"),
    DELETE("删除订单");

    private final String desc;

    OrderStateEvent(String desc) {
        this.desc = desc;
    }

    public String getDesc() {
        return desc;
    }
}
