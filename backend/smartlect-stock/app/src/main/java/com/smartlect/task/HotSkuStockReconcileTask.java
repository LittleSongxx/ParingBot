package com.smartlect.task;

import com.smartlect.component.HotSkuStockGate;
import com.xxl.job.core.handler.annotation.XxlJob;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 热点库存对账（ADR-0010）：桶总和与 DB 快照不一致时，只在没有活跃预占的 SKU 上按 DB 重建。
 * 默认关闭（smartlect.stock.hot-path.enabled=false）时任务直接返回。
 */
@Component
@Slf4j
public class HotSkuStockReconcileTask {

    @Resource
    private HotSkuStockGate hotSkuStockGate;

    @XxlJob("hotStockReconcile")
    public void reconcile() {
        hotSkuStockGate.reconcileAll();
    }
}
