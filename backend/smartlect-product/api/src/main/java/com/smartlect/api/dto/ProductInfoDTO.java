package com.smartlect.api.dto;

import lombok.Data;

import java.math.BigDecimal;

@Data


public class ProductInfoDTO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;


    private String productId;

    private String productName;

    private String productDesc;

    private String cover;

    private String categoryId;

    private BigDecimal minPrice;

    private BigDecimal maxPrice;

    private Integer totalSale;

}
