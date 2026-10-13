package com.smartlect.api.vo;

public class OrderCountVO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;
    private String code;
    private Integer count;

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public Integer getCount() {
        return count;
    }

    public void setCount(Integer count) {
        this.count = count;
    }
}
