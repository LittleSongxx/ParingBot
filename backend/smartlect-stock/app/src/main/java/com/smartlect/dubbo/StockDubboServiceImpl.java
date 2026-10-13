package com.smartlect.dubbo;

import com.smartlect.api.dubbo.StockDubboService;
import com.smartlect.controller.internal.StockInternalController;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboService;

import java.util.List;

/**
 * 库存域 Dubbo provider：直接委托 StockInternalController（与 HTTP 通道共用
 * @Valid 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class StockDubboServiceImpl implements StockDubboService {

    @Resource
    private StockInternalController stockInternalController;

    @Override
    public ResponseVO<SkuStockDTO> getStock(SkuStockQueryDTO dto) {
        return stockInternalController.getStock(dto);
    }

    @Override
    public ResponseVO<List<SkuStockDTO>> getStockBatch(List<SkuStockQueryDTO> items) {
        return stockInternalController.getStockBatch(items);
    }

    @Override
    public ResponseVO<StockChangeResultVO> changeStock(SkuStockChangeDTO dto) {
        return stockInternalController.changeStock(dto);
    }

    @Override
    public ResponseVO<StockChangeResultVO> changeStockBatch(SkuStockBatchChangeDTO dto) {
        return stockInternalController.changeStockBatch(dto);
    }

    @Override
    public ResponseVO<StockChangeResultVO> restoreRefundStock(RefundStockRestoreDTO dto) {
        return stockInternalController.restoreRefundStock(dto);
    }

    @Override
    public ResponseVO<StockChangeResultVO> restoreOrderStock(OrderStockRestoreDTO dto) {
        return stockInternalController.restoreOrderStock(dto);
    }

    @Override
    public ResponseVO<Boolean> isOrderStockApplied(OrderStockRestoreDTO dto) {
        return stockInternalController.isOrderStockApplied(dto);
    }

    @Override
    public ResponseVO<Boolean> isRefundStockApplied(RefundStockRestoreDTO dto) {
        return stockInternalController.isRefundStockApplied(dto);
    }

    @Override
    public ResponseVO<Void> setStock(SkuStockSetDTO dto) {
        return stockInternalController.setStock(dto);
    }

    @Override
    public ResponseVO<ProductTotalStockVO> totalByProduct(ProductIdDTO dto) {
        return stockInternalController.totalByProduct(dto);
    }

    @Override
    public ResponseVO<List<ProductTotalStockVO>> totalByProducts(List<String> productIds) {
        return stockInternalController.totalByProducts(productIds);
    }

    @Override
    public ResponseVO<PaginationResultVO<SkuStockDTO>> listLessThan(LessStockPageDTO dto) {
        return stockInternalController.listLessThan(dto);
    }
}
