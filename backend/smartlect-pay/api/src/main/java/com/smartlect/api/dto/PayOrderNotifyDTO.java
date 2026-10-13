package com.smartlect.api.dto;

public class PayOrderNotifyDTO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;

    private String payOrderId;

    private String channelOrderId;

    private PayOrderNotifyDTO() {
    }

    public PayOrderNotifyDTO(String payOrderId, String channelOrderId) {
        this.payOrderId = payOrderId;
        this.channelOrderId = channelOrderId;
    }

    public String getPayOrderId() {
        return payOrderId;
    }

    public void setPayOrderId(String payOrderId) {
        this.payOrderId = payOrderId;
    }

    public String getChannelOrderId() {
        return channelOrderId;
    }

    public void setChannelOrderId(String channelOrderId) {
        this.channelOrderId = channelOrderId;
    }
}
