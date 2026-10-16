package com.smartlect.compensation;

import com.smartlect.entity.po.ProductItem;

import java.util.List;

public interface StockBatchCompensatePort {

    int changeStockBatch(List<ProductItem> items);

    /**
     * 带业务幂等键的批量变更：补偿重放必须走这个重载——没有幂等键时重放会重复加库存
     * （2026-10-16 审计 H3：REMOTE_STOCK_CHANGE_BATCH 重放此前传 null 键，直接 apply）。
     */
    int changeStockBatch(List<ProductItem> items, String businessKey);

    int restoreOrderStock(String payOrderId, List<ProductItem> items);
}
