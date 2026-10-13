package com.smartlect.dubbo;

import com.smartlect.api.dubbo.ProductDubboService;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import com.smartlect.controller.internal.ProductInternalController;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * product 域 Dubbo provider：直接委托 internal controller（与 HTTP 通道共用
 * 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class ProductDubboServiceImpl implements ProductDubboService {

    @Resource
    private ProductInternalController productInternalController;

    @Override
    public ResponseVO<ProductSnapshotBatchVO> snapshotBatch(ProductIdListDTO dto) {
        return productInternalController.snapshotBatch(dto);
    }

    @Override
    public ResponseVO<ProductSkuSnapshotVO> defaultSku(ProductIdDTO dto) {
        return productInternalController.defaultSku(dto);
    }

    @Override
    public ResponseVO<Void> increaseSales(ProductSalesIncreaseDTO dto) {
        return productInternalController.increaseSales(dto);
    }

    @Override
    public ResponseVO<PaginationResultVO<ProductSkuListVO>> lessStockSkuPage(LessStockPageDTO dto) {
        return productInternalController.lessStockSkuPage(dto);
    }

    @Override
    public ResponseVO<java.util.List<String>> listOnSaleProductIds() {
        return productInternalController.listOnSaleProductIds();
    }

}
