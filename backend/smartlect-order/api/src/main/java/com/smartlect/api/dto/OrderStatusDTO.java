package com.smartlect.api.dto;

import com.smartlect.api.enums.OrderStatusEnum;

public class OrderStatusDTO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;
    private Integer status;
    private String desc;

    public Integer getStatus() {
        return status;
    }

    public void setStatus(Integer status) {
        this.status = status;
    }

    public String getDesc() {
        return desc;
    }

    public void setDesc(String desc) {
        this.desc = desc;
    }

    public static OrderStatusDTO getByStatus(OrderStatusEnum status){
        OrderStatusDTO orderStatusDTO = new OrderStatusDTO();
        orderStatusDTO.setStatus(status.getStatus());
        orderStatusDTO.setDesc(status.getDesc());
        return orderStatusDTO;
    }
}
