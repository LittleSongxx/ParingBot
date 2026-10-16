package com.smartlect.api.support;



import com.smartlect.api.dubbo.ProductDubboService;

import com.smartlect.api.dto.LessStockPageDTO;
import com.smartlect.api.dto.ProductIdDTO;
import com.smartlect.api.dto.ProductIdListDTO;
import com.smartlect.api.dto.ProductSalesIncreaseDTO;
import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.vo.ProductInfoSnapshotVO;
import com.smartlect.api.vo.ProductPropertyValueSnapshotVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.api.vo.ProductSkuListVO;
import jakarta.annotation.Resource;

import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;



import java.util.Collections;

import java.util.HashMap;

import java.util.LinkedHashMap;

import java.util.List;

import java.util.Map;

import java.util.function.Function;

import java.util.stream.Collectors;



@Component

public class ProductRpcSupport {



    @DubboReference

    private ProductDubboService productDubboService;

    @Resource

    private RpcResponseSupport rpcResponseSupport;



    public ProductSnapshotBatchVO snapshotBatch(List<String> productIds) {

        if (productIds == null || productIds.isEmpty()) {

            ProductSnapshotBatchVO empty = new ProductSnapshotBatchVO();

            empty.setProducts(Collections.emptyList());

            empty.setSkus(Collections.emptyList());

            empty.setPropertyValues(Collections.emptyList());

            return empty;

        }

        return rpcResponseSupport.call(

                () -> productDubboService.snapshotBatch(new ProductIdListDTO(productIds)),

                "查询商品快照失败");

    }



    public Map<String, ProductInfoSnapshotVO> toProductInfoMap(ProductSnapshotBatchVO batch) {

        if (batch == null || batch.getProducts() == null) {

            return new HashMap<>();

        }

        return batch.getProducts().stream()

                .collect(Collectors.toMap(ProductInfoSnapshotVO::getProductId, Function.identity(), (a, b) -> b));

    }



    public Map<String, ProductPropertyValueSnapshotVO> toPropertyValueMap(ProductSnapshotBatchVO batch) {

        if (batch == null || batch.getPropertyValues() == null) {

            return new HashMap<>();

        }

        return batch.getPropertyValues().stream()

                .collect(Collectors.toMap(

                        item -> item.getProductId() + item.getPropertyValueId(),

                        Function.identity(),

                        (a, b) -> b));

    }



    public Map<String, ProductSkuSnapshotVO> toSkuMapByPropertyValueIds(ProductSnapshotBatchVO batch) {

        if (batch == null || batch.getSkus() == null) {

            return new HashMap<>();

        }

        return batch.getSkus().stream()

                .collect(Collectors.toMap(

                        item -> item.getProductId() + nullToEmpty(item.getPropertyValueIds()),

                        Function.identity(),

                        (a, b) -> b));

    }



    public Map<String, ProductSkuSnapshotVO> toDefaultSkuByProductId(ProductSnapshotBatchVO batch) {

        Map<String, ProductSkuSnapshotVO> map = new LinkedHashMap<>();

        if (batch == null || batch.getSkus() == null) {

            return map;

        }

        for (ProductSkuSnapshotVO sku : batch.getSkus()) {

            map.putIfAbsent(sku.getProductId(), sku);

        }

        return map;

    }



    public ProductSkuSnapshotVO defaultSku(String productId) {

        return rpcResponseSupport.call(

                () -> productDubboService.defaultSku(new ProductIdDTO(productId)), "查询默认SKU失败");

    }



    public void increaseSales(String productId, int qty) {

        rpcResponseSupport.run(

                () -> productDubboService.increaseSales(new ProductSalesIncreaseDTO(productId, qty)),

                "增加销量失败");

    }

    public PaginationResultVO<ProductSkuListVO> lessStockSkuPage(Integer pageNo, Integer pageSize, Integer threshold) {
        return rpcResponseSupport.call(
                () -> productDubboService.lessStockSkuPage(new LessStockPageDTO(pageNo, pageSize, threshold)),
                "查询低库存商品失败");
    }

    public List<String> listOnSaleProductIds() {
        List<String> ids = rpcResponseSupport.call(
                productDubboService::listOnSaleProductIds,
                "查询在售商品ID失败");
        return ids == null ? Collections.emptyList() : ids;
    }

    private static String nullToEmpty(String s) {

        return s == null ? "" : s;

    }

}

