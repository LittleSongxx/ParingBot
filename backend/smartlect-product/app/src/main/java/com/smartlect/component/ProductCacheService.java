package com.smartlect.component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.smartlect.entity.vo.Product4VO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * 商品详情多级缓存（Caffeine L1 + Redis L2）。
 *
 * <p>主流电商详情页标配（Caffeine W-TinyLFU + Redis + 发布/订阅失效广播）：
 * L1 拦截热点读（进程内纳秒级），L2 跨实例共享（毫秒级），写路径先删 L2 再广播
 * 失效事件让所有实例清 L1。库存不进缓存（架构原则：交易事实以 Java 查询时点为准），
 * 仅缓存商品静态信息（基础 + 属性 + SKU 规格）。</p>
 *
 * <p>降级语义：Redis 不可达时 L1 仍可用（仅本实例命中率下降）；
 * 两者都不可达时调用方直查 DB（调用方视为 miss）。</p>
 */
@Slf4j
@Service
public class ProductCacheService {

    public static final String INVALIDATION_CHANNEL = "smartlect:product:invalidate";
    private static final String KEY_PREFIX = "smartlect:product:detail:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Cache<String, Product4VO> l1;

    @Value("${smartlect.cache.l2-ttl-seconds:300}")
    private long l2TtlSeconds;

    public ProductCacheService(StringRedisTemplate redisTemplate,
                               ObjectMapper objectMapper,
                               @Value("${smartlect.cache.l1-maximum-size:10000}") int l1MaximumSize,
                               @Value("${smartlect.cache.l1-expire-after-write-seconds:60}") long l1ExpireSeconds) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.l1 = Caffeine.newBuilder()
                .maximumSize(l1MaximumSize)
                .expireAfterWrite(l1ExpireSeconds, TimeUnit.SECONDS)
                .build();
    }

    /** 读：L1 → L2 → miss（调用方查 DB 后调 put 回填）。库存字段由调用方实时补，不进缓存。 */
    public Product4VO get(String productId) {
        Product4VO cached = l1.getIfPresent(productId);
        if (cached != null) {
            return cached;
        }
        try {
            String json = redisTemplate.opsForValue().get(KEY_PREFIX + productId);
            if (json != null) {
                Product4VO value = objectMapper.readValue(json, Product4VO.class);
                l1.put(productId, value);
                return value;
            }
        } catch (Exception e) {
            log.debug("L2 读失败 productId={}：{}（L1 仍可用，继续 miss）", productId, e.getMessage());
        }
        return null;
    }

    /** 写：回填 L2 + L1（不广播——写方自己知道，广播仅在失效时发）。 */
    public void put(String productId, Product4VO value) {
        // 库存清零后再入缓存：防止调用方未清就回填带旧库存的快照
        Product4VO snapshot = stripVolatileStock(value);
        l1.put(productId, snapshot);
        try {
            String json = objectMapper.writeValueAsString(snapshot);
            // TTL 加 ±10% 抖动防雪崩（同一时刻大量 key 过期打崩 DB）
            long jitter = (long) (l2TtlSeconds * (0.9 + Math.random() * 0.2));
            redisTemplate.opsForValue().set(KEY_PREFIX + productId, json,
                    Duration.ofSeconds(Math.max(jitter, 30)));
        } catch (Exception e) {
            log.debug("L2 写失败 productId={}：{}（L1 已写，仅本实例可用）", productId, e.getMessage());
        }
    }

    /** 失效：删 L2 + 广播清所有实例 L1（写路径与 Canal 消费者均调用）。 */
    public void invalidate(String productId) {
        l1.invalidate(productId);
        try {
            redisTemplate.delete(KEY_PREFIX + productId);
            redisTemplate.convertAndSend(INVALIDATION_CHANNEL, productId);
        } catch (Exception e) {
            log.debug("失效广播失败 productId={}：{}（L1 已清，其他实例靠 TTL 收敛）", productId, e.getMessage());
        }
    }

    /** 订阅失效广播（RedisMessageListenerContainer 配置调用）。 */
    public void onInvalidationMessage(String productId) {
        l1.invalidate(productId);
    }

    /** 库存清零：缓存的是静态快照，库存字段设 0 防调用方误用旧值（真实库存由调用方实时 RPC 查）。 */
    private Product4VO stripVolatileStock(Product4VO value) {
        if (value.getSkuList() != null) {
            value.getSkuList().forEach(sku -> sku.setStock(0));
        }
        return value;
    }

    public Cache<String, Product4VO> l1Cache() {
        return l1;
    }
}
