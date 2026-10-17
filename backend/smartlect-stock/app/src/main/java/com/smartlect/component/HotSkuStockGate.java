package com.smartlect.component;

import com.smartlect.config.HotStockProperties;
import com.smartlect.domain.SkuStock;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.SkuStockMapper;
import com.smartlect.metrics.SmartlectMetrics;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 热点库存预占原型（ADR-0010，默认关闭）。
 *
 * <p>只对配置里的 SKU 生效：Redis 用 Lua 在多个桶上原子扣减并写 reservation；
 * 随后仍执行 DB 条件更新，DB 始终是事实源。Redis 不可用时直接回退 DB 条件更新，
 * 不会因为缓存故障阻断下单；数据库的 {@code stock + delta >= 0} 仍是最后一道防超卖。
 * 预占标记带 TTL，进程崩溃后的悬挂预占由对账任务在无活跃标记时按 DB 重置。</p>
 */
@Component
@Slf4j
public class HotSkuStockGate {

    private static final String PREFIX = "smartlect:stock:hot:";

    private final HotStockProperties properties;
    private final StringRedisTemplate redis;
    private final SkuStockMapper stockMapper;
    private final SmartlectMetrics metrics;
    private final Map<String, SkuRef> refs = new LinkedHashMap<>();
    private DefaultRedisScript<Long> reserveScript;
    private DefaultRedisScript<Long> releaseScript;

    public HotSkuStockGate(HotStockProperties properties, StringRedisTemplate redis,
                           SkuStockMapper stockMapper, SmartlectMetrics metrics) {
        this.properties = properties;
        this.redis = redis;
        this.stockMapper = stockMapper;
        this.metrics = metrics;
    }

    @PostConstruct
    void initialize() {
        for (String configured : properties.getSkus()) {
            if (configured == null || configured.isBlank()) {
                continue;
            }
            int separator = configured.indexOf(':');
            if (separator <= 0 || separator == configured.length() - 1) {
                log.warn("忽略非法的热点库存 SKU 配置: {}", configured);
                continue;
            }
            String productId = configured.substring(0, separator).trim();
            String hash = configured.substring(separator + 1).trim();
            SkuRef ref = new SkuRef(productId, hash, token(productId, hash));
            refs.put(skuKey(productId, hash), ref);
        }
        properties.setBuckets(Math.max(1, Math.min(properties.getBuckets(), 16)));
        reserveScript = script("lua/hot_stock_reserve_v1.lua");
        releaseScript = script("lua/hot_stock_release_v1.lua");
        if (properties.isEnabled()) {
            log.info("热点库存原型已启用：skus={}, buckets={}, reservationTtl={}s",
                    refs.size(), properties.getBuckets(), properties.getReservationTtlSeconds());
        }
    }

    public boolean isEnabled() {
        return properties.isEnabled() && !refs.isEmpty();
    }

    public boolean isHot(String productId, String propertyValueIdHash) {
        return refs.containsKey(skuKey(productId, propertyValueIdHash));
    }

    /**
     * 在 DB 条件更新之前预占；Redis 故障时回退（fail-open），库存不足时抛业务异常。
     *
     * @param orderKey 与 DB 扣减幂等键一致，如 {@code order-deduct:pay-1}
     * @param changes  SKU → 带符号数量（负数为扣减）
     */
    public void reserve(String orderKey, Map<String, Integer> changes) {
        if (!isEnabled() || orderKey == null || changes == null || changes.isEmpty()) {
            return;
        }
        List<SkuRef> reserved = new ArrayList<>();
        try {
            List<Map.Entry<String, Integer>> entries = new ArrayList<>(changes.entrySet());
            entries.sort(Comparator.comparing(Map.Entry::getKey));
            for (Map.Entry<String, Integer> entry : entries) {
                int delta = entry.getValue() == null ? 0 : entry.getValue();
                SkuRef ref = refs.get(entry.getKey());
                if (ref == null || delta >= 0) {
                    continue;
                }
                ensureInitialized(ref);
                Long result = redis.execute(reserveScript, reservationAndBucketKeys(ref, orderKey),
                        String.valueOf(-delta), String.valueOf(ttlSeconds()));
                if (result == null || result < 0) {
                    releaseAll(orderKey, reserved);
                    metrics.hotStockReserve("insufficient");
                    throw new BusinessException("库存不足");
                }
                reserved.add(ref);
            }
            if (!reserved.isEmpty()) {
                metrics.hotStockReserve("reserved");
            }
        } catch (BusinessException ex) {
            throw ex;
        } catch (RuntimeException ex) {
            releaseAll(orderKey, reserved);
            metrics.hotStockReserve("fallback");
            log.warn("热点库存预占失败，回退 DB 条件更新 orderKey={}", orderKey, ex);
        }
    }

    /** DB 条件更新成功：删除预占标记但保留桶扣减，表示库存已经真实卖出。 */
    public void commit(String orderKey, Map<String, Integer> changes) {
        if (!isEnabled() || orderKey == null || changes == null) {
            return;
        }
        for (Map.Entry<String, Integer> entry : changes.entrySet()) {
            SkuRef ref = refs.get(entry.getKey());
            if (ref == null) {
                continue;
            }
            try {
                redis.delete(reservationKey(ref, orderKey));
            } catch (RuntimeException ex) {
                log.warn("热点库存预占提交失败，标记将等待 TTL 过期 orderKey={}, sku={}",
                        orderKey, entry.getKey(), ex);
            }
        }
    }

    /** DB 条件更新失败时只释放预占，不补桶（否则会把未扣过的库存加回去）。 */
    public void release(String orderKey, Map<String, Integer> changes) {
        if (!isEnabled() || orderKey == null || changes == null) {
            return;
        }
        for (Map.Entry<String, Integer> entry : changes.entrySet()) {
            SkuRef ref = refs.get(entry.getKey());
            if (ref == null) {
                continue;
            }
            try {
                releaseOne(ref, orderKey);
            } catch (RuntimeException ex) {
                log.warn("热点库存预占释放失败，等待 TTL/对账 orderKey={}, sku={}",
                        orderKey, entry.getKey(), ex);
            }
        }
    }

    /** 关单回补：优先释放预占；预占已过期/不存在时按数量回补桶。 */
    public void restoreOrder(String payOrderId, Map<String, Integer> changes) {
        if (!isEnabled() || payOrderId == null || changes == null) {
            return;
        }
        String orderKey = "order-deduct:" + payOrderId;
        for (Map.Entry<String, Integer> entry : changes.entrySet()) {
            SkuRef ref = refs.get(entry.getKey());
            if (ref == null || entry.getValue() == null) {
                continue;
            }
            try {
                if (releaseOne(ref, orderKey) == 0) {
                    replenish(ref, Math.abs(entry.getValue()));
                }
            } catch (RuntimeException ex) {
                log.warn("热点库存关单回补失败，等待对账 payOrderId={}, sku={}", payOrderId, entry.getKey(), ex);
            }
        }
    }

    /** 退款回补：只在 Redis 已初始化时增加，避免对历史订单凭空造桶。 */
    public void replenish(String productId, String propertyValueIdHash, int amount) {
        SkuRef ref = refs.get(skuKey(productId, propertyValueIdHash));
        if (!isEnabled() || ref == null || amount <= 0) {
            return;
        }
        try {
            if (!Boolean.TRUE.equals(redis.hasKey(readyKey(ref)))) {
                return;
            }
            redis.opsForValue().increment(bucketKey(ref, 0), amount);
        } catch (RuntimeException ex) {
            log.warn("热点库存退款回补失败，等待对账 sku={}", skuKey(productId, propertyValueIdHash), ex);
        }
    }

    /** 管理端改库存后调用：无活跃预占时按 DB 重建桶。 */
    public void reconcileSku(String productId, String propertyValueIdHash) {
        SkuRef ref = refs.get(skuKey(productId, propertyValueIdHash));
        if (!isEnabled() || ref == null) {
            return;
        }
        try {
            if (hasActiveReservation(ref)) {
                return;
            }
            List<String> bucketKeys = new ArrayList<>();
            int redisTotal = 0;
            for (int i = 0; i < properties.getBuckets(); i++) {
                String key = bucketKey(ref, i);
                bucketKeys.add(key);
                redisTotal += intValue(redis.opsForValue().get(key));
            }
            int dbStock = dbStock(ref);
            if (redisTotal != dbStock) {
                metrics.hotStockReconcileDiff();
                log.warn("热点库存桶与 DB 不一致，按 DB 重建 sku={}, redis={}, db={}",
                        skuKey(ref.productId(), ref.hash()), redisTotal, dbStock);
            }
            redis.delete(bucketKeys);
            redis.delete(readyKey(ref));
            ensureInitialized(ref);
        } catch (RuntimeException ex) {
            log.warn("热点库存重建失败 sku={}", skuKey(productId, propertyValueIdHash), ex);
        }
    }

    public void reconcileAll() {
        if (!isEnabled()) {
            return;
        }
        for (SkuRef ref : refs.values()) {
            reconcileSku(ref.productId(), ref.hash());
        }
    }

    private void releaseAll(String orderKey, List<SkuRef> refsToRelease) {
        for (SkuRef ref : refsToRelease) {
            try {
                releaseOne(ref, orderKey);
            } catch (RuntimeException ex) {
                log.warn("热点库存预占回滚失败，等待 TTL/对账 orderKey={}, sku={}",
                        orderKey, skuKey(ref.productId(), ref.hash()), ex);
            }
        }
    }

    private long releaseOne(SkuRef ref, String orderKey) {
        Long released = redis.execute(releaseScript,
                List.of(reservationKey(ref, orderKey), bucketKey(ref, 0)));
        return released == null ? 0 : released;
    }

    private void replenish(SkuRef ref, int amount) {
        if (amount <= 0) {
            return;
        }
        redis.opsForValue().increment(bucketKey(ref, 0), amount);
    }

    private void ensureInitialized(SkuRef ref) {
        if (Boolean.TRUE.equals(redis.hasKey(readyKey(ref)))) {
            return;
        }
        int total = dbStock(ref);
        int buckets = properties.getBuckets();
        int base = total / buckets;
        int remainder = total % buckets;
        for (int i = 0; i < buckets; i++) {
            int value = base + (i < remainder ? 1 : 0);
            redis.opsForValue().setIfAbsent(bucketKey(ref, i), String.valueOf(value));
        }
        redis.opsForValue().setIfAbsent(readyKey(ref), "1");
    }

    private boolean hasActiveReservation(SkuRef ref) {
        Set<String> keys = redis.keys(PREFIX + ref.token() + ":reservation:*");
        return keys != null && !keys.isEmpty();
    }

    private int dbStock(SkuRef ref) {
        SkuStock row = stockMapper.selectByKey(ref.productId(), ref.hash());
        return row == null || row.getStock() == null ? 0 : row.getStock();
    }

    private List<String> reservationAndBucketKeys(SkuRef ref, String orderKey) {
        List<String> keys = new ArrayList<>(properties.getBuckets() + 1);
        keys.add(reservationKey(ref, orderKey));
        for (int i = 0; i < properties.getBuckets(); i++) {
            keys.add(bucketKey(ref, i));
        }
        return keys;
    }

    private String reservationKey(SkuRef ref, String orderKey) {
        return PREFIX + ref.token() + ":reservation:" + orderKey;
    }

    private String bucketKey(SkuRef ref, int bucket) {
        return PREFIX + ref.token() + ":bucket:" + bucket;
    }

    private String readyKey(SkuRef ref) {
        return PREFIX + ref.token() + ":ready";
    }

    private long ttlSeconds() {
        return Math.max(60, properties.getReservationTtlSeconds());
    }

    private static int intValue(String value) {
        try {
            return value == null ? 0 : Integer.parseInt(value);
        } catch (NumberFormatException ex) {
            return 0;
        }
    }

    private static String skuKey(String productId, String hash) {
        return productId + "\0" + hash;
    }

    private static String token(String productId, String hash) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(skuKey(productId, hash).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, 24);
        } catch (Exception ex) {
            throw new IllegalStateException("无法生成热点库存 key", ex);
        }
    }

    private static DefaultRedisScript<Long> script(String location) {
        DefaultRedisScript<Long> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource(location));
        script.setResultType(Long.class);
        return script;
    }

    private record SkuRef(String productId, String hash, String token) {
    }
}
