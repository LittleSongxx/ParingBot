package com.smartlect.entity.po;

import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/** 订单状态变更历史；只追加，不更新。 */
@Data
public class OrderStatusLog implements Serializable {

    private Long logId;
    private String orderId;
    private String payOrderId;
    private Integer fromStatus;
    private Integer toStatus;
    private String event;
    private String operatorType;
    private String operatorId;
    private String requestId;
    private String remark;
    private Date createTime;
}
