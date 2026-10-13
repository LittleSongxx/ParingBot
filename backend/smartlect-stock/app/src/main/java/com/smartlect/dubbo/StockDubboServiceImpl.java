package com.smartlect.dubbo;

import com.smartlect.api.dubbo.StockDubboService;
import com.smartlect.controller.internal.StockInternalController;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * 库存域 Dubbo provider：直接委托 StockInternalController（与 HTTP 通道共用
 * @Valid 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class StockDubboServiceImpl implements StockDubboService {

    @Resource
    private StockInternalController stockInternalController;

    @Override
    public ResponseVO<com.smartlect.api.dto.SkuStockDTO> getStock(com.smartlect.api.dto.SkuStockQueryDTO dto) {
        return stockInternalController.getStock(dto);
    }

    @Override
    public ResponseVO<java.util.List<com.smartlect.api.dto.SkuStockDTO>> getStockBatch(java.util.List<com.smartlect.api.dto.SkuStockQueryDTO> items) {
        return stockInternalController.getStockBatch(items);
    }

    @Override
    public ResponseVO<com.smartlect.api.vo.StockChangeResultVO> changeStock(com.smartlect.api.dto.SkuStockChangeDTO dto) {
        return stockInternalController.changeStock(dto);
    }

    @Override
    public ResponseVO<com.smartlect.api.vo.StockChangeResultVO> changeStockBatch(com.smartlect.api.dto.SkuStockBatchChangeDTO dto) {
        return stockInternalController.changeStockBatch(dto);
    }

    @Override
    public ResponseVO<com.smartlect.api.vo.StockChangeResultVO> restoreRefundStock(com.smartlect.api.dto.RefundStockRestoreDTO dto) {
        return stockInternalController.restoreRefundStock(dto);
    }

    @Override
    public ResponseVO<com.smartlect.api.vo.StockChangeResultVO> restoreOrderStock(com.smartlect.api.dto.OrderStockRestoreDTO dto) {
        return stockInternalController.restoreOrderStock(dto);
    }

    @Override
    public ResponseVO<Boolean> isOrderStockApplied(com.smartlect.api.dto.OrderStockRestoreDTO dto) {
        return stockInternalController.isOrderStockApplied(dto);
    }

    @Override
    public ResponseVO<Boolean> isRefundStockApplied(com.smartlect.api.dto.RefundStockRestoreDTO dto) {
        return stockInternalController.isRefundStockApplied(dto);
    }

    @Override
    public ResponseVO<Void> setStock(com.smartlect.api.dto.SkuStockSetDTO dto) {
        return stockInternalController.setStock(dto);
    }

    @Override
    public ResponseVO<com.smartlect.api.vo.ProductTotalStockVO> totalByProduct(com.smartlect.api.dto.ProductIdDTO dto) {
        return stockInternalController.totalByProduct(dto);
    }

    @Override
    public ResponseVO<java.util.List<com.smartlect.api.vo.ProductTotalStockVO>> totalByProducts(java.util.List<String> productIds) {
        return stockInternalController.totalByProducts(productIds);
    }

    @Override
    public ResponseVO<com.smartlect.entity.vo.PaginationResultVO<com.smartlect.api.dto.SkuStockDTO>> listLessThan(com.smartlect.api.dto.LessStockPageDTO dto) {
        return stockInternalController.listLessThan(dto);
    }
}
