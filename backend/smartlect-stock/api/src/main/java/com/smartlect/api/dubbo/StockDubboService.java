package com.smartlect.api.dubbo;

import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.OrderStockRestoreDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.dto.SkuStockBatchChangeDTO;
import com.smartlect.api.dto.SkuStockChangeDTO;
import com.smartlect.api.dto.SkuStockDTO;
import com.smartlect.api.dto.SkuStockQueryDTO;
import com.smartlect.api.dto.SkuStockSetDTO;
import com.smartlect.api.vo.ProductTotalStockVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;

import java.util.List;

/**
 * 库存域内部 Dubbo 契约（取代 StockFeignClient，方法签名一致；HTTP /internal/stock
 * 端点保留给 assistant 与运维，双通道共用同一 Service 层）。
 */
public interface StockDubboService {

    ResponseVO<SkuStockDTO> getStock(SkuStockQueryDTO dto);

    ResponseVO<List<SkuStockDTO>> getStockBatch(List<SkuStockQueryDTO> items);

    ResponseVO<StockChangeResultVO> changeStock(SkuStockChangeDTO dto);

    ResponseVO<StockChangeResultVO> changeStockBatch(SkuStockBatchChangeDTO dto);

    ResponseVO<StockChangeResultVO> restoreRefundStock(RefundStockRestoreDTO dto);

    ResponseVO<StockChangeResultVO> restoreOrderStock(OrderStockRestoreDTO dto);

    ResponseVO<Boolean> isOrderStockApplied(OrderStockRestoreDTO dto);

    ResponseVO<Boolean> isRefundStockApplied(RefundStockRestoreDTO dto);

    ResponseVO<Void> setStock(SkuStockSetDTO dto);

    ResponseVO<ProductTotalStockVO> totalByProduct(ProductIdDTO dto);

    ResponseVO<List<ProductTotalStockVO>> totalByProducts(List<String> productIds);

    ResponseVO<PaginationResultVO<SkuStockDTO>> listLessThan(LessStockPageDTO dto);
}
