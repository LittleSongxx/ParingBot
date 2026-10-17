package com.smartlect.controller;

import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.biz.ProductInfoService;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PublicProductSearchTest {
    private ProductController controller;
    private ProductInfoService service;

    @BeforeEach
    void setUp() {
        controller = new ProductController();
        service = mock(ProductInfoService.class);
        when(service.findListByPage(any())).thenReturn(new PaginationResultVO<>());
        ReflectionTestUtils.setField(controller, "productInfoService", service);
        // 默认桩：ES 不可达（null）→ 控制器走 SQL LIKE 回退路径，保住既有契约断言
        com.smartlect.search.ProductIndexService index = mock(com.smartlect.search.ProductIndexService.class);
        when(index.searchIdsByKeyword(any(), any(), org.mockito.ArgumentMatchers.anyInt())).thenReturn(null);
        ReflectionTestUtils.setField(controller, "productIndexService", index);
    }

    private ProductInfoQuery capture() {
        ArgumentCaptor<ProductInfoQuery> captor = ArgumentCaptor.forClass(ProductInfoQuery.class);
        verify(service).findListByPage(captor.capture());
        return captor.getValue();
    }

    @Test
    void esKeywordHitShortCircuitsToProductIdList() {
        com.smartlect.search.ProductIndexService index = mock(com.smartlect.search.ProductIndexService.class);
        when(index.searchIdsByKeyword(any(), any(), org.mockito.ArgumentMatchers.anyInt()))
                .thenReturn(java.util.List.of("P1", "P2"));
        ReflectionTestUtils.setField(controller, "productIndexService", index);
        controller.loadProduct(1, null, "键盘", null, null, null, null, null);
        ProductInfoQuery query = capture();
        assertNull(query.getProductNameFuzzy());
        assertEquals(List.of("P1", "P2"), query.getProductIdList());
    }

    @Test
    void emptyEsHitsYieldEmptyPageWithoutFallingBackToAllProducts() {
        com.smartlect.search.ProductIndexService index = mock(com.smartlect.search.ProductIndexService.class);
        when(index.searchIdsByKeyword(any(), any(), org.mockito.ArgumentMatchers.anyInt()))
                .thenReturn(java.util.List.of());
        ReflectionTestUtils.setField(controller, "productIndexService", index);

        ResponseVO response = controller.loadProduct(1, null, "不存在的关键词", null, null, null, null, null);

        assertNotNull(response.getData());
        PaginationResultVO<?> page = (PaginationResultVO<?>) response.getData();
        assertEquals(0, page.getTotalCount());
        assertTrue(page.getList().isEmpty());
        // 空 ID 集不能交给 Mapper；否则 <if size>0> 会退化成返回全部在售商品。
        verify(service, never()).findListByPage(any());
    }

    @Test
    void keywordSearchesTheWholeOnSaleCatalogueInsteadOfCommendedOnly() {
        controller.loadProduct(1, null, "  键盘  ", null, null, null, null, null);
        ProductInfoQuery query = capture();
        assertEquals("键盘", query.getProductNameFuzzy());
        assertEquals(ProductStatusEnum.ON_SALE.getStatus(), query.getStatus());
        // A search must not stay inside the commended landing list, or most matches vanish.
        assertNull(query.getCommendType());
        assertEquals(Boolean.TRUE, query.getExcludeIsolatedCatalog());
    }

    @Test
    void blankKeywordKeepsTheCommendedLandingList() {
        controller.loadProduct(1, null, "   ", null, null, null, null, null);
        ProductInfoQuery query = capture();
        assertNull(query.getProductNameFuzzy());
        assertEquals(Integer.valueOf(0), query.getCommendType());
    }

    @Test
    void absentKeywordKeepsTheCommendedLandingList() {
        controller.loadProduct(1, null, null, null, null, null, null, null);
        ProductInfoQuery query = capture();
        assertNull(query.getProductNameFuzzy());
        assertEquals(Integer.valueOf(0), query.getCommendType());
    }

    @Test
    void keywordCombinesWithCategoryAndPriceWithoutLosingEitherFilter() {
        controller.loadProduct(2, "phones", "键盘", new BigDecimal("10.00"), new BigDecimal("99.99"), null, null, null);
        ProductInfoQuery query = capture();
        assertEquals("键盘", query.getProductNameFuzzy());
        assertEquals("phones", query.getCategoryIdOrPCategoryId());
        assertEquals(new BigDecimal("10.00"), query.getPriceFrom());
        assertEquals(new BigDecimal("99.99"), query.getPriceTo());
        assertEquals(Integer.valueOf(2), query.getPageNo());
        assertEquals(ProductStatusEnum.ON_SALE.getStatus(), query.getStatus());
    }

    @Test
    void excludeProductIdsDropOutOfScopeCatalogueRows() {
        controller.loadProduct(1, null, null, null, null, null, null, "930000000081301, bad id, 910000000000000");
        ProductInfoQuery query = capture();
        assertEquals(List.of("930000000081301", "910000000000000"), query.getExcludeProductIdList());
    }
}
