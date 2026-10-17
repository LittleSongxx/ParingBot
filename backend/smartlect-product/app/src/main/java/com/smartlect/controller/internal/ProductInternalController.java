package com.smartlect.controller.internal;

import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.ProductIdListDTO;
import com.smartlect.api.dto.ProductSalesIncreaseDTO;
import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.biz.ProductInternalService;
import com.smartlect.biz.ProductSkuService;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductSkuListVO;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/internal/product")
public class ProductInternalController extends ABaseController {

    @Resource
    private ProductInternalService productInternalService;

    @Resource
    private ProductSkuService productSkuService;

    @PostMapping("/snapshotBatch")
    public ResponseVO<ProductSnapshotBatchVO> snapshotBatch(@Valid @RequestBody ProductIdListDTO dto) {
        return getSuccessResponseVO(productInternalService.snapshotBatch(
                dto == null ? null : dto.getProductIds()));
    }

    @PostMapping("/defaultSku")
    public ResponseVO<ProductSkuSnapshotVO> defaultSku(@Valid @RequestBody ProductIdDTO dto) {
        return getSuccessResponseVO(productInternalService.defaultSku(dto.getProductId()));
    }

    @PostMapping("/increaseSales")
    public ResponseVO<Void> increaseSales(@Valid @RequestBody ProductSalesIncreaseDTO dto) {
        if (dto != null) {
            productInternalService.increaseSales(dto.getProductId(),
                    dto.getQty() == null ? 0 : dto.getQty());
        }
        return getSuccessResponseVO(null);
    }

    @PostMapping("/lessStockSkuPage")
    public ResponseVO<PaginationResultVO<ProductSkuListVO>> lessStockSkuPage(@RequestBody LessStockPageDTO dto) {
        if (dto == null) {
            dto = new LessStockPageDTO();
        }
        return getSuccessResponseVO(productSkuService.lessStockSkuPage(
                dto.getPageNo(), dto.getPageSize(), dto.getThreshold()));
    }

    @PostMapping("/listOnSaleProductIds")
    public ResponseVO<List<String>> listOnSaleProductIds(
            @org.springframework.web.bind.annotation.RequestParam(required = false) String productIdPrefix) {
        return getSuccessResponseVO(productInternalService.listOnSaleProductIds(productIdPrefix));
    }

    public ResponseVO<List<String>> listOnSaleProductIds() {
        return listOnSaleProductIds(null);
    }
}
