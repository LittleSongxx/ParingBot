package com.smartlect.component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.vo.Product4VO;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * 缓存隔离回归网：缓存里只放「库存清零的静态快照」，且缓存实例绝不交给调用方。
 *
 * <p>对应两处真实缺陷：① put 曾在调用方对象上原地清零，导致冷启动首访详情把
 * stock=0 返回给前端；② get 曾直接返回 L1 实例，调用方补实时库存时会污染缓存条目。</p>
 */
class ProductCacheStockIsolationTest {

    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    private final ObjectMapper objectMapper = new ObjectMapper();

    @SuppressWarnings("unchecked")
    private ValueOperations<String, String> valueOps() {
        ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        return ops;
    }

    private ProductCacheService service() {
        return new ProductCacheService(redis, objectMapper, 128, 60);
    }

    private Product4VO detailWithStock(int stock) {
        ProductSku sku = new ProductSku();
        sku.setProductId("895150981058759");
        sku.setPropertyValueIdHash("137e14ea51a28c111aef8b2258c3691f");
        sku.setPropertyValueIds("1780554968348-1780554968349");
        sku.setPrice(new BigDecimal("8999.00"));
        sku.setSort(0);
        sku.setStock(stock);
        Product4VO vo = new Product4VO();
        vo.setSkuList(List.of(sku));
        return vo;
    }

    @Test
    void missPathKeepsRealtimeStockForCallerWhileCacheStoresZeroedSnapshot() {
        valueOps();
        ProductCacheService cache = service();
        Product4VO callerVo = detailWithStock(564);

        cache.put("895150981058759", callerVo);

        // 调用方对象必须原样保留实时库存（miss 路径紧接着把它返回给前端）
        assertEquals(564, callerVo.getSkuList().get(0).getStock());
        Product4VO cached = cache.l1Cache().getIfPresent("895150981058759");
        assertNotNull(cached);
        assertNotSame(callerVo, cached);
        assertNotSame(callerVo.getSkuList().get(0), cached.getSkuList().get(0));
        assertEquals(0, cached.getSkuList().get(0).getStock());
    }

    @Test
    void l1HitReturnsCopySoReplenishCannotPolluteCachedSnapshot() {
        valueOps();
        ProductCacheService cache = service();
        cache.put("895150981058759", detailWithStock(564));

        Product4VO first = cache.get("895150981058759");
        assertNotNull(first);
        first.getSkuList().get(0).setStock(3);   // 模拟命中路径补实时库存

        assertEquals(0, cache.l1Cache().getIfPresent("895150981058759")
                .getSkuList().get(0).getStock());

        Product4VO second = cache.get("895150981058759");
        assertEquals(0, second.getSkuList().get(0).getStock(), "上一请求补的库存不得泄漏给下一请求");
        assertNotSame(first, second);
    }

    @Test
    void l2HitAlsoReturnsACopy() throws Exception {
        ValueOperations<String, String> ops = valueOps();
        String json = objectMapper.writeValueAsString(detailWithStock(0));
        when(ops.get(anyString())).thenReturn(json);
        ProductCacheService cache = service();

        Product4VO hit = cache.get("895150981058759");
        assertNotNull(hit);
        hit.getSkuList().get(0).setStock(9);

        assertEquals(0, cache.l1Cache().getIfPresent("895150981058759")
                .getSkuList().get(0).getStock());
        verify(ops, times(1)).get(anyString());
    }

    @Test
    void putWritesZeroedSnapshotToRedisWithTtl() {
        ValueOperations<String, String> ops = valueOps();
        ProductCacheService cache = service();

        cache.put("895150981058759", detailWithStock(564));

        verify(ops).set(eq("smartlect:product:detail:895150981058759"), contains("\"stock\":0"),
                any(Duration.class));
    }

    @Test
    void redisFailureFallsBackToMissInsteadOfThrowing() {
        ValueOperations<String, String> ops = valueOps();
        when(ops.get(anyString())).thenThrow(new RuntimeException("connection refused"));
        ProductCacheService cache = service();

        assertNull(cache.get("895150981058759"), "Redis 不可达时调用方应视作 miss 并回源 DB");
    }
}
