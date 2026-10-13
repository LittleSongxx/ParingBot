package com.smartlect.api.dto;

public class PayOrderMessageDTO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;

    public PayOrderMessageDTO(String orderId) {
        this.orderId = orderId;
    }

    public PayOrderMessageDTO() {
    }

    public String orderId;

    private Integer logisticsStep;

    public String getOrderId() {
        return orderId;
    }

    public void setOrderId(String orderId) {
        this.orderId = orderId;
    }

    public Integer getLogisticsStep() {
        return logisticsStep;
    }

    public void setLogisticsStep(Integer logisticsStep) {
        this.logisticsStep = logisticsStep;
    }
}
