package com.smartlect.search;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch.core.SearchRequest;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.mappers.ProductInfoMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 锁住「检索谓词的形状」——它与 SQL LIKE 的语义等价性是合同，也是 hybrid 打分腿的开关边界。
 *
 * <p>为什么要专门测形状：本索引只当 ID 集过滤器用（排序/分页在 DB），一旦谓词被无意放宽成
 * 分词命中，搜索结果会静默变多（v16 评测踩过这个坑），普通功能测试很难发现。</p>
 */
class ProductIndexQueryShapeTest {

    @SuppressWarnings("unchecked")
    private final ProductInfoMapper<ProductInfo, ProductInfoQuery> mapper = mock(ProductInfoMapper.class);

    /**
     * 用"捕获请求后抛 IOException"短路：既拿到真实构造出来的 SearchRequest，
     * 又不用伪造一份完整的 SearchResponse（服务对 IOException 的契约就是回退信号 null）。
     */
    private ProductIndexService serviceWithMode(AtomicReference<SearchRequest> captured, String mode) throws IOException {
        ElasticsearchClient client = mock(ElasticsearchClient.class);
        when(client.search(any(SearchRequest.class), eq(Map.class))).thenAnswer(invocation -> {
            captured.set(invocation.getArgument(0));
            throw new IOException("query captured by test");
        });
        ProductIndexService service = new ProductIndexService(client, mapper);
        ReflectionTestUtils.setField(service, "searchMode", mode);
        return service;
    }

    @Test
    void substringModeKeepsLikeEquivalentWildcardOnly() throws IOException {
        AtomicReference<SearchRequest> captured = new AtomicReference<>();
        ProductIndexService service = serviceWithMode(captured, ProductIndexService.MODE_SUBSTRING);

        List<String> ids = service.searchIdsByKeyword("WH-1000XX", List.of(), 50);

        assertNull(ids, "ES 不可用时应返回 null（调用方回退 SQL LIKE）");
        var must = captured.get().query().bool().must();
        assertEquals(1, must.size(), "文本谓词应只有一个 must 子句");
        var textPredicate = must.get(0).bool();
        assertNotNull(textPredicate, "文本谓词是 bool.should 组合");
        assertEquals(1, textPredicate.should().size(), "substring 模式：只有子串腿");
        var leg = textPredicate.should().get(0);
        assertTrue(leg.isWildcard(), "子串腿必须是 wildcard");
        assertEquals("productName.raw", leg.wildcard().field());
        assertTrue(leg.wildcard().caseInsensitive());
        assertEquals("*WH-1000XX*", leg.wildcard().wildcard(), "大小写不敏感 + 两端通配 = LIKE '%kw%'");
        assertTrue(textPredicate.should().stream().noneMatch(q -> q.isMatch()), "substring 模式不得出现分词腿");
        assertEquals("1", textPredicate.minimumShouldMatch());
    }

    @Test
    void hybridModeAddsAnalyzedLegsOnTopOfSubstringLeg() throws IOException {
        AtomicReference<SearchRequest> captured = new AtomicReference<>();
        ProductIndexService service = serviceWithMode(captured, ProductIndexService.MODE_HYBRID);

        service.searchIdsByKeyword("降噪 头戴式", List.of(), 50);

        var should = captured.get().query().bool().must().get(0).bool().should();
        assertEquals(3, should.size(), "hybrid：子串腿 + 商品名分词腿 + 描述分词腿");
        assertEquals(1, should.stream().filter(q -> q.isWildcard()).count(), "子串腿始终保留（召回是超集）");
        assertEquals(1, should.stream()
                .filter(q -> q.isMatch() && "productName".equals(q.match().field())).count());
        assertEquals(1, should.stream()
                .filter(q -> q.isMatch() && "productDesc".equals(q.match().field())).count());
    }

    @Test
    void defaultModeIsSubstringAndUnknownValuesFallBackToIt() throws IOException {
        AtomicReference<SearchRequest> captured = new AtomicReference<>();
        ProductIndexService defaulted = serviceWithMode(captured, "substring");
        assertEquals(ProductIndexService.MODE_SUBSTRING, defaulted.searchMode());

        ProductIndexService unknown = serviceWithMode(new AtomicReference<>(), "does-not-exist");
        assertEquals(ProductIndexService.MODE_SUBSTRING, unknown.searchMode(), "非法模式回落到默认");
    }
}
