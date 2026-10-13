package com.smartlect.api.dubbo;

import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;

/**
 * product 域内部 Dubbo 契约（取代原 FeignClient，方法签名一致；
 * HTTP /internal 端点保留给 assistant 与运维，双通道共用同一 Service 层）。
 */
public interface ProductDubboService {

    ResponseVO<ProductSnapshotBatchVO> snapshotBatch(ProductIdListDTO dto);

    ResponseVO<ProductSkuSnapshotVO> defaultSku(ProductIdDTO dto);

    ResponseVO<Void> increaseSales(ProductSalesIncreaseDTO dto);

    ResponseVO<PaginationResultVO<ProductSkuListVO>> lessStockSkuPage(LessStockPageDTO dto);

    ResponseVO<java.util.List<String>> listOnSaleProductIds();

}
