package com.smartlect.biz.impl;

import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.component.ProductBloomFilterComponent;
import com.smartlect.entity.dto.ProductSaveDTO;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * saveProduct 携带属性值图集（propertyGallery）的持久化语义：
 * 新增走 insertBatch 原样落库；编辑按 propertyValueId 三路分发；
 * 「清空图集必须显式传空串」依赖 updateBatch 的 if 只判 null 不判空串——
 * 这里同时锁住传递值与 XML 条件，防止未来把 != null 改成 != '' 导致清不掉。
 */
class SaveProductGalleryTest {
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
        // saveProduct 末尾注册 afterCommit 同步，单测无事务上下文需手动开启
        TransactionSynchronizationManager.initSynchronization();
    }

    @AfterEach
    void tearDown() {
        TransactionSynchronizationManager.clearSynchronization();
    }

    private ProductPropertyValue value(String valueId, String gallery) {
        ProductPropertyValue pv = new ProductPropertyValue();
        pv.setPropertyId("1001");
        pv.setPropertyName("颜色");
        pv.setPropertySort(1);
        pv.setCoverType(1);
        pv.setPropertyValueId(valueId);
        pv.setPropertyCover("2026-06/card.jpg");
        pv.setPropertyGallery(gallery);
        pv.setPropertyValue("星夜银");
        return pv;
    }

    private ProductSku sku(String hash) {
        ProductSku sku = new ProductSku();
        sku.setPropertyValueIdHash(hash);
        sku.setPropertyValueIds("v1-s1");
        sku.setPrice(new BigDecimal("10.00"));
        return sku;
    }

    private ProductSaveDTO dto(ProductInfo info, List<ProductPropertyValue> values, List<ProductSku> skus) {
        ProductSaveDTO dto = new ProductSaveDTO();
        dto.setProductInfo(info);
        dto.setProductPropertyList(values);
        dto.setSkuList(skus);
        return dto;
    }

    private ProductInfo info(String productId) {
        ProductInfo info = new ProductInfo();
        info.setProductId(productId);
        info.setProductName("测试商品");
        return info;
    }

    @Test
    void addProductPersistsValueGalleriesViaInsertBatch() {
        service.saveProduct(dto(info(null),
                List.of(value("v1", "2026-06/a.jpg,2026-06/b.jpg")),
                List.of(sku("h1"))));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<ProductPropertyValue>> captor = ArgumentCaptor.forClass(List.class);
        verify(propertyValueMapper).insertBatch(captor.capture());
        assertEquals("2026-06/a.jpg,2026-06/b.jpg", captor.getValue().get(0).getPropertyGallery());
        // 15 位随机 productId 已回填到属性值上
        assertEquals(15, captor.getValue().get(0).getProductId().length());
    }

    @Test
    void updateRoutesByValueIdAndCarriesEmptyStringGallery() {
        when(propertyValueMapper.selectList(any())).thenReturn(List.of(value("v1", "2026-06/old.jpg"), value("v2", "")));
        when(productSkuMapper.selectList(any())).thenReturn(List.of(sku("h1")));

        service.saveProduct(dto(info("053997047858558"),
                List.of(value("v1", ""), value("v3", "2026-06/new.jpg")),
                List.of(sku("h1"))));

        // v1 更新（清空图集=空串原样传给 updateBatch）、v3 新增、v2 删除
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<ProductPropertyValue>> updateCaptor = ArgumentCaptor.forClass(List.class);
        verify(propertyValueMapper).updateBatch(eq("053997047858558"), updateCaptor.capture());
        assertEquals("v1", updateCaptor.getValue().get(0).getPropertyValueId());
        assertEquals("", updateCaptor.getValue().get(0).getPropertyGallery());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<ProductPropertyValue>> addCaptor = ArgumentCaptor.forClass(List.class);
        verify(propertyValueMapper).insertBatch(addCaptor.capture());
        assertEquals("v3", addCaptor.getValue().get(0).getPropertyValueId());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<ProductPropertyValue>> deleteCaptor = ArgumentCaptor.forClass(List.class);
        verify(propertyValueMapper).deleteBatch(eq("053997047858558"), deleteCaptor.capture());
        assertEquals("v2", deleteCaptor.getValue().get(0).getPropertyValueId());
    }

    @Test
    void updateBatchXmlTreatsNullAsSkipButEmptyStringAsClear() throws Exception {
        // 锁住 XML 语义：清空图集传空串必须落库（if 只判 null），传 null 才跳过
        Path xml = Path.of("src/main/resources/com/smartlect/mappers/ProductPropertyValueMapper.xml");
        String content = Files.readString(xml);
        assertTrue(content.contains("<if test=\"item.propertyGallery != null\">"),
                "updateBatch 对 propertyGallery 的条件必须是 != null，改成 != '' 会让空串清空失效");
    }

    @Test
    void afterCommitOnlyAddsNewProductsToBloomFilter() {
        service.saveProduct(dto(info("053997047858558"),
                List.of(value("v1", "")), List.of(sku("h1"))));

        List<TransactionSynchronization> syncs = TransactionSynchronizationManager.getSynchronizations();
        assertEquals(1, syncs.size());
        syncs.get(0).afterCommit();
        verify(bloomFilter, org.mockito.Mockito.never()).add(any());
    }
}
