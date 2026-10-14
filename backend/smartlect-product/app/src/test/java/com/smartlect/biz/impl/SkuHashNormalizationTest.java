package com.smartlect.biz.impl;

import com.smartlect.entity.dto.ProductSaveDTO;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.exception.BusinessException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** SKU 指纹服务端重算（ADR-0022）：不一致覆写为权威值，重复指纹拒绝。 */
@ExtendWith(MockitoExtension.class)
class SkuHashNormalizationTest {

    @InjectMocks
    private ProductInfoServiceImpl service;

    private static ProductSaveDTO dto(ProductSku... skus) {
        ProductSaveDTO dto = new ProductSaveDTO();
        dto.setSkuList(List.of(skus));
        return dto;
    }

    private static ProductSku sku(String propertyValueIds, String hash) {
        ProductSku sku = new ProductSku();
        sku.setPropertyValueIds(propertyValueIds);
        sku.setPropertyValueIdHash(hash);
        return sku;
    }

    @Test
    void forgedHashIsOverwrittenByAuthoritativeValue() {
        ProductSku sku = sku("101-202", "forged-hash");
        org.springframework.test.util.ReflectionTestUtils.invokeMethod(service, "normalizeSkuHashes", dto(sku));
        assertEquals(com.smartlect.utils.StringTools.encodeByMD5("101-202"), sku.getPropertyValueIdHash());
    }

    @Test
    void duplicateSpecCombinationsAreRejected() {
        ProductSku first = sku("101-202", null);
        first.setPropertyValueIdHash(com.smartlect.utils.StringTools.encodeByMD5("101-202"));
        ProductSku second = sku("101-202", com.smartlect.utils.StringTools.encodeByMD5("101-202"));
        assertThrows(BusinessException.class, () ->
                org.springframework.test.util.ReflectionTestUtils.invokeMethod(
                        service, "normalizeSkuHashes", dto(first, second)));
    }

    @Test
    void emptyPropertyValueIdsIsRejected() {
        assertThrows(BusinessException.class, () ->
                org.springframework.test.util.ReflectionTestUtils.invokeMethod(
                        service, "normalizeSkuHashes", dto(sku("", "x"))));
    }
}
