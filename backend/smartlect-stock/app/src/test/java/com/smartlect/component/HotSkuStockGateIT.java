package com.smartlect.component;

import com.smartlect.config.HotStockProperties;
import com.smartlect.domain.SkuStock;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.SkuStockMapper;
import com.smartlect.metrics.SmartlectMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 热点库存原型的真 Redis 回归（ADR-0010）：桶预占、幂等、库存不足不落桶、释放/回补与按 DB 重建。
 * DB 仍是事实源：这里只验证 Redis 门闩，不替代 SkuStockService 的条件更新测试。
 */
@Testcontainers
class HotSkuStockGateIT {

    private static final String SKU = "p1";
    private static final String HASH = "sku1";
    private static final String MAP_KEY = SKU + "\0" + HASH;

    @Container
    static final GenericContainer<?> REDIS = new GenericContainer<>(DockerImageName.parse("redis:7.2-alpine"))
            .withExposedPorts(6379);

    static LettuceConnectionFactory factory;

    StringRedisTemplate redis;
    HotSkuStockGate gate;
    SimpleMeterRegistry registry;

    @BeforeAll
    static void connect() {
        factory = new LettuceConnectionFactory(
                new RedisStandaloneConfiguration(REDIS.getHost(), REDIS.getMappedPort(6379)));
        factory.afterPropertiesSet();
    }

    @AfterAll
    static void disconnect() {
        if (factory != null) {
            factory.destroy();
        }
    }

    @BeforeEach
    void setUp() {
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();
        redis.getConnectionFactory().getConnection().serverCommands().flushAll();
        registry = new SimpleMeterRegistry();
        SkuStockMapper mapper = mock(SkuStockMapper.class);
        SkuStock row = new SkuStock();
        row.setProductId(SKU);
        row.setPropertyValueIdHash(HASH);
        row.setStock(5);
        when(mapper.selectByKey(anyString(), anyString())).thenReturn(row);

        HotStockProperties properties = new HotStockProperties();
        properties.setEnabled(true);
        properties.setSkus(List.of(SKU + ":" + HASH));
        properties.setBuckets(3);
        properties.setReservationTtlSeconds(60);
        gate = new HotSkuStockGate(properties, redis, mapper, new SmartlectMetrics(registry));
        gate.initialize();
    }

    @Test
    void reserveIsAtomicAndIdempotentPerOrder() {
        gate.reserve("order-deduct:pay-1", Map.of(MAP_KEY, -3));
        assertEquals(2, bucketTotal());
        gate.reserve("order-deduct:pay-1", Map.of(MAP_KEY, -3));
        assertEquals(2, bucketTotal(), "同一订单重复预占不能二次扣桶");

        assertThrows(BusinessException.class,
                () -> gate.reserve("order-deduct:pay-2", Map.of(MAP_KEY, -3)));
        assertEquals(2, bucketTotal(), "库存不足时不能留下部分扣减");
        assertTrue(registry.get("smartlect_stock_hot_reserve_total").tag("result", "insufficient")
                .counter().count() >= 1);
    }

    @Test
    void commitKeepsBucketDecrementButRemovesMarker() {
        gate.reserve("order-deduct:pay-commit", Map.of(MAP_KEY, -3));
        gate.commit("order-deduct:pay-commit", Map.of(MAP_KEY, -3));
        assertEquals(2, bucketTotal());
        assertEquals(0, activeReservationCount());
    }

    @Test
    void releaseAndCloseRestorePutReservationBack() {
        gate.reserve("order-deduct:pay-3", Map.of(MAP_KEY, -3));
        gate.release("order-deduct:pay-3", Map.of(MAP_KEY, -3));
        assertEquals(5, bucketTotal());

        gate.reserve("order-deduct:pay-4", Map.of(MAP_KEY, -2));
        gate.restoreOrder("pay-4", Map.of(MAP_KEY, 2));
        assertEquals(5, bucketTotal());
        assertEquals(0, activeReservationCount());
    }

    @Test
    void reconcileResetsDriftOnlyWhenNoActiveReservation() {
        gate.reserve("order-deduct:pay-init", Map.of(MAP_KEY, -1));
        gate.release("order-deduct:pay-init", Map.of(MAP_KEY, -1));
        gate.replenish(SKU, HASH, 2);
        assertEquals(7, bucketTotal());
        gate.reconcileSku(SKU, HASH);
        assertEquals(5, bucketTotal());
        assertEquals(1.0, registry.get("smartlect_stock_hot_reconcile_diff_total").counter().count());

        gate.reserve("order-deduct:pay-5", Map.of(MAP_KEY, -1));
        redis.opsForValue().set(firstBucketKey(), "999");
        gate.reconcileSku(SKU, HASH);
        assertEquals("999", redis.opsForValue().get(firstBucketKey()),
                "有活跃预占时不得按 DB 重建，避免踩掉正在下单的库存");
    }

    @Test
    void disabledFlagKeepsGateClosed() {
        HotStockProperties disabled = new HotStockProperties();
        disabled.setEnabled(false);
        disabled.setSkus(List.of(SKU + ":" + HASH));
        HotSkuStockGate off = new HotSkuStockGate(disabled, redis, mock(SkuStockMapper.class),
                new SmartlectMetrics(registry));
        off.initialize();
        assertFalse(off.isEnabled());
        off.reserve("order-deduct:pay-6", Map.of(MAP_KEY, -1));
        assertEquals(0, redis.keys("smartlect:stock:hot:*").size());
    }

    private int bucketTotal() {
        Set<String> keys = redis.keys("smartlect:stock:hot:*:bucket:*");
        if (keys == null) {
            return 0;
        }
        int total = 0;
        for (String key : keys) {
            String value = redis.opsForValue().get(key);
            total += value == null ? 0 : Integer.parseInt(value);
        }
        return total;
    }

    private int activeReservationCount() {
        Set<String> keys = redis.keys("smartlect:stock:hot:*:reservation:*");
        return keys == null ? 0 : keys.size();
    }

    private String firstBucketKey() {
        Set<String> keys = redis.keys("smartlect:stock:hot:*:bucket:0");
        return keys.iterator().next();
    }
}
