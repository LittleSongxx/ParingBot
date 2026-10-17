package com.smartlect.task;

import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.search.ProductIndexService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

/**
 * 商品索引初始化：索引为空、缺文档或显式要求时全量重建，否则跳过。
 *
 * <p>Canal 只管增量且位点从订阅时刻开始——全新部署的存量商品必须由本初始化器补进索引，
 * 停摆期间漏掉的文档也要靠它补。但"每次启动都重建 87k 条"既慢又掩盖问题：运行时用
 * ES 文档数与在售商品数比较，只有索引更少（缺文档）才重建。</p>
 *
 * <p>已知盲区：等量的"内容陈旧"（Canal 漏了一次 upsert、条数不变）检测不到；
 * 需要时把 {@code smartlect.canal.index-force-rebuild} 设为 true 重启一次。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "smartlect.canal.index-enabled", havingValue = "true", matchIfMissing = true)
public class ProductIndexInitializer implements ApplicationRunner {

    private final ProductIndexService indexService;
    private final ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper;

    @Value("${smartlect.canal.index-force-rebuild:false}")
    private boolean forceRebuild;

    public ProductIndexInitializer(ProductIndexService indexService,
            ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper) {
        this.indexService = indexService;
        this.productInfoMapper = productInfoMapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        // 异步执行：重建需要数分钟，阻塞主线程会拖死健康检查（曾导致启动超时被杀）。
        // 检索在索引就绪前自动回退 SQL LIKE，服务可用性不受重建进度影响。
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("product-index-init-");
        executor.setDaemon(true);
        executor.initialize();
        executor.execute(this::initializeIndex);
    }

    /** 包可见，便于单测同步调用（run 只负责调度）。 */
    void initializeIndex() {
        if (!indexService.ensureIndex()) {
            log.warn("ES 不可达，商品索引初始化跳过（查询将回退 SQL LIKE，待 ES 恢复后重启补全）");
            return;
        }
        long esCount = indexService.count();
        if (forceRebuild) {
            log.info("index-force-rebuild=true，执行全量重建（当前索引 {} 条）", esCount);
            indexService.rebuildAll(500);
            return;
        }
        if (esCount < 0) {
            // -1 = ES 读不到文档数（聚类/权限/瞬时故障）。不能当作"非空"静默跳过。
            log.warn("无法读取商品索引文档数，按缺失处理并重建");
            indexService.rebuildAll(500);
            return;
        }
        if (esCount == 0) {
            log.info("商品索引为空，执行全量重建");
            indexService.rebuildAll(500);
            return;
        }
        long dbCount = countOnSaleProducts();
        if (esCount < dbCount) {
            log.info("商品索引缺文档（ES {} 条 < 在售 {} 条），执行全量重建", esCount, dbCount);
            indexService.rebuildAll(500);
            return;
        }
        log.info("商品索引已就绪（ES {} 条 ≥ 在售 {} 条），跳过启动重建", esCount, dbCount);
    }

    private long countOnSaleProducts() {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setStatus(ProductStatusEnum.ON_SALE.getStatus());
        return com.smartlect.utils.PageUtils.pageInfo(1, 1,
                () -> productInfoMapper.selectList(query)).getTotal();
    }
}
