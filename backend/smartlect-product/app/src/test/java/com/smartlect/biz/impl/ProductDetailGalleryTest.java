package com.smartlect.biz.impl;

import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.component.ProductBloomFilterComponent;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.entity.vo.Product4VO;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 详情接口必须把按属性值配置的图集（property_gallery）原样透传给前端，
 * 否则「选颜色切换整组图」拿不到数据。这里锁住透传语义，不测其它组装细节。
 */
class ProductDetailGalleryTest {
    private final ProductInfoServiceImpl service = new ProductInfoServiceImpl();
    @SuppressWarnings("unchecked")
    private final ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper = mock(ProductInfoMapper.class);
    @SuppressWarnings("unchecked")
    private final ProductPropertyValueMapper<ProductPropertyValue, ProductPropertyValueQuery> propertyValueMapper =
            mock(ProductPropertyValueMapper.class);
    @SuppressWarnings("unchecked")
    private final ProductSkuMapper<ProductSku, ProductSkuQuery> productSkuMapper = mock(ProductSkuMapper.class);
    private final ProductBloomFilterComponent bloomFilter = mock(ProductBloomFilterComponent.class);
    private final StockRpcSupport stockRpcSupport = mock(StockRpcSupport.class);

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(service, "productInfoMapper", productInfoMapper);
        ReflectionTestUtils.setField(service, "productPropertyValueMapper", propertyValueMapper);
        ReflectionTestUtils.setField(service, "productSkuMapper", productSkuMapper);
        ReflectionTestUtils.setField(service, "productBloomFilterComponent", bloomFilter);
        ReflectionTestUtils.setField(service, "stockRpcSupport", stockRpcSupport);
        com.smartlect.component.ProductCacheService cacheService =
                mock(com.smartlect.component.ProductCacheService.class);
        ReflectionTestUtils.setField(service, "productCacheService", cacheService);
        when(bloomFilter.mightExist(any())).thenReturn(true);
        when(productSkuMapper.selectList(any())).thenReturn(List.of());
        when(stockRpcSupport.getAvailableBatch(anyList())).thenReturn(java.util.Map.of());
    }

    private ProductPropertyValue value(String propertyId, String valueId, String cover, String gallery) {
        ProductPropertyValue pv = new ProductPropertyValue();
        pv.setProductId("p1");
        pv.setPropertyId(propertyId);
        pv.setPropertyName("颜色");
        pv.setPropertySort(1);
        pv.setCoverType(1);
        pv.setPropertyValueId(valueId);
        pv.setPropertyCover(cover);
        pv.setPropertyGallery(gallery);
        pv.setPropertyValue("星夜银");
        return pv;
    }

    @Test
    void detailPassesPerValueGalleryThroughToPropertyValues() {
        ProductInfo info = new ProductInfo();
        info.setProductId("p1");
        when(productInfoMapper.selectByProductId("p1")).thenReturn(info);
        when(propertyValueMapper.selectList(any())).thenReturn(List.of(
                value("1001", "v1", "2026-06/silver.jpg", "2026-06/silver.jpg,2026-06/silver-back.jpg"),
                value("1001", "v2", "2026-06/blue.jpg", null)));

        Product4VO vo = service.getProduct4VOByProductId("p1");

        assertEquals(1, vo.getProductPropertyList().size());
        List<?> values = vo.getProductPropertyList().get(0).getPropertyValues();
        assertEquals(2, values.size());
        com.smartlect.api.vo.ProductPropertyValueVO silver =
                (com.smartlect.api.vo.ProductPropertyValueVO) values.get(0);
        com.smartlect.api.vo.ProductPropertyValueVO blue =
                (com.smartlect.api.vo.ProductPropertyValueVO) values.get(1);
        assertEquals("2026-06/silver.jpg,2026-06/silver-back.jpg", silver.getPropertyGallery());
        assertEquals("2026-06/silver.jpg", silver.getPropertyCover());
        assertNull(blue.getPropertyGallery());
        assertEquals("2026-06/blue.jpg", blue.getPropertyCover());
    }
}
