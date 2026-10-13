package com.smartlect.search;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.component.ProductIndexConsumer;
import com.smartlect.entity.po.ProductInfo;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 商品索引纯函数契约：wildcard 转义（用户输入即字面量，与 LIKE 语义一致）、
 * canal 行解析（字段映射、DELETE 镜像、时间格式）、文档字段换算。
 */
class ProductIndexServiceTest {

    @Test
    void escapeWildcardTreatsUserInputAsLiteral() {
        assertEquals("a\\*b", ProductIndexService.escapeWildcard("a*b"));
        assertEquals("x\\?y", ProductIndexService.escapeWildcard("x?y"));
        assertEquals("a\\\\b", ProductIndexService.escapeWildcard("a\\b"));
        assertEquals("普通词", ProductIndexService.escapeWildcard("普通词"));
    }

    @Test
    void centsConversionHandlesNullAndScale() {
        assertEquals(0L, ProductIndexService.cents(null));
        assertEquals(12900L, ProductIndexService.cents(new BigDecimal("129.00")));
        assertEquals(1L, ProductIndexService.cents(new BigDecimal("0.01")));
    }

    @Test
    void canalRowMapsToIndexDocument() throws Exception {
        String flat = """
                {"database":"smartlect_product","table":"product_info","type":"UPDATE",
                 "data":[{"product_id":"P1","product_name":"金属机械键盘","product_desc":null,
                          "cover":"c.png","brand":null,"category_id":"S91","p_category_id":"S90",
                          "status":1,"min_price":"399.00","max_price":"399.00","total_sale":"3",
                          "commend_type":"1","catalog_scope":null,
                          "create_time":"2026-08-01 10:00:00"}],
                 "pkNames":["product_id"]}""";
        ProductInfo product = ProductIndexConsumer.fromCanalRow(
                new ObjectMapper().readTree(flat).path("data").get(0), "P1");
        assertEquals("P1", product.getProductId());
        assertEquals("金属机械键盘", product.getProductName());
        assertEquals("S91", product.getCategoryId());
        assertEquals(new BigDecimal("399.00"), product.getMinPrice());
        assertEquals(3, product.getTotalSale());
        assertEquals(1, product.getStatus());
        assertNull(product.getCatalogScope()); // toDocument 侧兜底为 store
        assertEquals(0L, ProductIndexService.cents(null));
        var doc = ProductIndexService.toDocument(product);
        assertEquals("store", doc.get("catalogScope"));
        assertEquals(39900L, doc.get("minPriceCents"));
    }

    @Test
    void consumerIgnoresOtherTablesAndMissingRows() throws IOException {
        ProductIndexConsumer consumer = new ProductIndexConsumer(null, new ObjectMapper(), null);
        consumer.consume("{\"table\":\"product_sku\",\"type\":\"UPDATE\",\"data\":[{\"product_id\":\"P1\"}]}");
        consumer.consume("{\"table\":\"product_info\",\"type\":\"UPDATE\",\"data\":[]}");
    }
}
