package com.smartlect.search;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.BulkRequest;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.mappers.ProductInfoMapper;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 全量重建必须按 keyset 翻页，不能复用对外分页（100/500 上限会把 250 条截成 100 条）。
 */
class ProductIndexRebuildTest {

    @Test
    void rebuildAllReadsEveryProductAcrossBatches() throws Exception {
        @SuppressWarnings("unchecked")
        ProductInfoMapper<ProductInfo, ProductInfoQuery> mapper = mock(ProductInfoMapper.class);
        ElasticsearchClient client = mock(ElasticsearchClient.class);
        List<ProductInfo> all = IntStream.range(0, 250).mapToObj(this::product).toList();
        when(mapper.selectForIndex(any(), eq(100))).thenAnswer(invocation -> {
            String lastId = invocation.getArgument(0);
            int start = lastId == null ? 0 : Integer.parseInt(lastId.substring(1)) + 1;
            if (start >= all.size()) {
                return List.of();
            }
            return all.subList(start, Math.min(start + 100, all.size()));
        });
        when(client.bulk(any(BulkRequest.class))).thenReturn(BulkResponse.of(b -> b.items(List.of()).errors(false).took(0L)));
        ProductIndexService service = spy(new ProductIndexService(client, mapper));
        doReturn(true).when(service).ensureIndex();

        int total = service.rebuildAll(100);

        assertEquals(250, total);
        // 100 + 100 + 50 三批；最后一批不足 pageSize，直接终止，不再多查一次空页。
        verify(client, times(3)).bulk(any(BulkRequest.class));
        verify(mapper, times(3)).selectForIndex(any(), eq(100));
    }

    private ProductInfo product(int index) {
        ProductInfo product = new ProductInfo();
        product.setProductId(String.format("P%03d", index));
        product.setProductName("商品 " + index);
        product.setStatus(1);
        product.setMinPrice(new BigDecimal("1.00"));
        product.setMaxPrice(new BigDecimal("1.00"));
        product.setCreateTime(new Date());
        return product;
    }
}
