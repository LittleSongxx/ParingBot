package com.smartlect.biz;

import com.smartlect.api.dto.ProductSnapshotBatchVO;
import com.smartlect.api.vo.ProductInfoSnapshotVO;
import com.smartlect.api.vo.ProductPropertyValueSnapshotVO;
import com.smartlect.api.vo.ProductSkuSnapshotVO;
import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.CollectionUtils;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class ProductInternalService {

    @Resource
    private ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper;
    @Resource
    private ProductSkuMapper<ProductSku, ProductSkuQuery> productSkuMapper;
    @Resource
    private ProductPropertyValueMapper<ProductPropertyValue, ProductPropertyValueQuery> productPropertyValueMapper;
    @Resource
    private StockRpcSupport stockRpcSupport;

    public ProductSnapshotBatchVO snapshotBatch(List<String> productIds) {
        ProductSnapshotBatchVO vo = new ProductSnapshotBatchVO();
        if (CollectionUtils.isEmpty(productIds)) {
            vo.setProducts(Collections.emptyList());
            vo.setSkus(Collections.emptyList());
            vo.setPropertyValues(Collections.emptyList());
            vo.setTotalStocks(Collections.emptyMap());
            return vo;
        }
        ProductInfoQuery productInfoQuery = new ProductInfoQuery();
        productInfoQuery.setProductIdList(productIds);
        List<ProductInfo> products = productInfoMapper.selectList(productInfoQuery);
        List<ProductInfoSnapshotVO> productVos = new ArrayList<>();
        for (ProductInfo p : products) {
            ProductInfoSnapshotVO item = new ProductInfoSnapshotVO();
            item.setProductId(p.getProductId());
            item.setProductName(p.getProductName());
            item.setStatus(p.getStatus());
            item.setCover(p.getCover());
            item.setMinPrice(p.getMinPrice());
            item.setMaxPrice(p.getMaxPrice());
            item.setCategoryId(p.getCategoryId());
            item.setTotalSale(p.getTotalSale());
            item.setCatalogScope(p.getCatalogScope());
            productVos.add(item);
        }
        vo.setProducts(productVos);

        ProductSkuQuery productSkuQuery = new ProductSkuQuery();
        productSkuQuery.setProductIdList(productIds);
        productSkuQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
        List<ProductSku> skus = productSkuMapper.selectList(productSkuQuery);
        List<ProductSkuSnapshotVO> skuVos = new ArrayList<>();
        for (ProductSku s : skus) {
            ProductSkuSnapshotVO item = new ProductSkuSnapshotVO();
            BeanUtils.copyProperties(s, item);
            skuVos.add(item);
        }
        vo.setSkus(skuVos);

        ProductPropertyValueQuery propertyValueQuery = new ProductPropertyValueQuery();
        propertyValueQuery.setProductIdList(productIds);
        List<ProductPropertyValue> pvs = productPropertyValueMapper.selectList(propertyValueQuery);
        List<ProductPropertyValueSnapshotVO> pvVos = new ArrayList<>();
        for (ProductPropertyValue pv : pvs) {
            ProductPropertyValueSnapshotVO item = new ProductPropertyValueSnapshotVO();
            item.setProductId(pv.getProductId());
            item.setPropertyValueId(pv.getPropertyValueId());
            item.setPropertyName(pv.getPropertyName());
            item.setPropertyValue(pv.getPropertyValue());
            item.setPropertyCover(pv.getPropertyCover());
            pvVos.add(item);
        }
        vo.setPropertyValues(pvVos);
        vo.setTotalStocks(stockRpcSupport.totalByProducts(productIds));
        return vo;
    }

    public ProductSkuSnapshotVO defaultSku(String productId) {
        if (StringTools.isEmpty(productId)) {
            throw new BusinessException("商品ID为空");
        }
        ProductSkuQuery query = new ProductSkuQuery();
        query.setProductId(productId);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
        List<ProductSku> list = productSkuMapper.selectList(query);
        if (list == null || list.isEmpty()) {
            return null;
        }
        ProductSkuSnapshotVO vo = new ProductSkuSnapshotVO();
        BeanUtils.copyProperties(list.get(0), vo);
        return vo;
    }

    @Transactional(rollbackFor = Exception.class)
    public void increaseSales(String productId, int qty) {
        if (StringTools.isEmpty(productId) || qty <= 0) {
            return;
        }
        Integer affected = productInfoMapper.increaseTotalSale(productId, qty);
        if (affected == null || affected == 0) {
            throw new BusinessException("商品不存在");
        }
    }

    public List<String> listOnSaleProductIds() {
        return listOnSaleProductIds(null);
    }

    /** prefix 只服务演示/压测夹具：避免为了 20 个演示商品把 8.7 万条在售 ID 全量拉进内存。 */
    public List<String> listOnSaleProductIds(String productIdPrefix) {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setStatus(ProductStatusEnum.ON_SALE.getStatus());
        if (productIdPrefix != null && !productIdPrefix.isBlank()) {
            query.setProductIdFuzzy(productIdPrefix.trim());
        }
        List<ProductInfo> list = productInfoMapper.selectList(query);
        if (list == null || list.isEmpty()) {
            return Collections.emptyList();
        }
        return list.stream().map(ProductInfo::getProductId).collect(Collectors.toList());
    }
}
