package com.smartlect.api.enums;

import java.util.Arrays;
import java.util.Optional;

public enum OrderStatusEnum {
    DELETE(-1, "已删除"),
    WAIT_PAYMENT(0, "待付款"),
    PAID(1, "已付款,待发货"),
    SHIPPED(2, "已发货"),
    COMPLETED(3, "已完成"),
    CANCELLED(4, "交易取消"),
    CLOSED(5, "交易关闭"),
    REFUNDED(6, "已退款,交易关闭"),
    PARTIALLY_REFUNDED(7, "部分退款");

    private Integer status;
    private String desc;

    OrderStatusEnum(Integer status, String desc) {
        this.status = status;
        this.desc = desc;
    }

    public Integer getStatus() {
        return status;
    }

    public String getDesc() {
        return desc;
    }


    public static OrderStatusEnum getByStatus(Integer status) {
        // 修复（ADR-0009）：旧写法 typeEnum == null 永假（Optional 不会为 null），
        // 未知状态会 .get() 抛 NoSuchElementException 而非返回 null
        return Arrays.stream(OrderStatusEnum.values())
                .filter(value -> value.getStatus().equals(status))
                .findFirst()
                .orElse(null);
    }
}
