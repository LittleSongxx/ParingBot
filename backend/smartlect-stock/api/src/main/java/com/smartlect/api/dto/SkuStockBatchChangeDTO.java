package com.smartlect.api.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;

import java.io.Serializable;
import java.util.List;

public class SkuStockBatchChangeDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    @NotEmpty
    @Valid
    private List<SkuStockChangeDTO> items;

    /**
     * Optional idempotency key for the whole batch (order deduct). Restore already
     * uses per-SKU keys; deduct must not double-apply after an RPC timeout replay.
     */
    private String businessKey;

    public List<SkuStockChangeDTO> getItems() {
        return items;
    }

    public void setItems(List<SkuStockChangeDTO> items) {
        this.items = items;
    }

    public String getBusinessKey() {
        return businessKey;
    }

    public void setBusinessKey(String businessKey) {
        this.businessKey = businessKey;
    }
}
