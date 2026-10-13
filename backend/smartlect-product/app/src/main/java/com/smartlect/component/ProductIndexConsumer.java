package com.smartlect.component;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.search.ProductIndexService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.math.BigDecimal;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

/**
 * Canal CDC 消费者：binlog（flat JSON，canal.serverMode=rocketMQ 直投 Topic）→
 * 商品索引增量同步。
 *
 * <p>同一 Topic 单消费组保序：canal 对同一行的变更按 binlog 顺序投递，逐条覆盖
 * 索引即为最终一致（无版本列，乱序风险由顺序消费消除；全量重建由初始化器兜底）。
 * 消息内按表名过滤（当前仅 product_info），非目标表直接丢弃。CDC 消费是幂等
 * upsert，跳过 Redis 租约；失败由容器统一延迟重试并归档审查表。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "smartlect.canal.index-enabled", havingValue = "true", matchIfMissing = true)
public class ProductIndexConsumer implements SmartlectMessageListener<String> {

    private final ProductIndexService indexService;
    private final ObjectMapper objectMapper;
    private final ProductCacheService cacheService;

    public ProductIndexConsumer(ProductIndexService indexService,
                                ObjectMapper objectMapper,
                                ProductCacheService cacheService) {
        this.indexService = indexService;
        this.objectMapper = objectMapper;
        this.cacheService = cacheService;
    }

    @Override
    public MqSubscription subscription() {
        // tag 为 null：canal 直投无 Tag，订阅 Topic 全量
        return MqSubscription.of(RocketMqTopics.TOPIC_CANAL, null, "G_smartlect_canal_product");
    }

    @Override
    public Class<String> payloadType() {
        return String.class;
    }

    @Override
    public long idempotencyTtlSeconds() {
        return 0;
    }

    @Override
    public void onMessage(String payload, SmartlectMqMessage message) throws IOException {
        consume(payload);
    }

    public void consume(String payload) throws IOException {
        JsonNode root = objectMapper.readTree(payload);
        String table = root.path("table").asText("");
        if (!"product_info".equals(table)) {
            return; // 订阅面扩大前，非商品主表一律忽略
        }
        String type = root.path("type").asText("");
        JsonNode rows = root.path("data");
        if (!rows.isArray() || rows.isEmpty()) {
            return;
        }
        // DELETE 事件的 data 为删除前镜像，同样按 id 覆盖/删除处理
        boolean delete = "DELETE".equalsIgnoreCase(type);
        List<String> touched = new ArrayList<>();
        for (JsonNode row : rows) {
            String productId = row.path("product_id").asText(null);
            if (productId == null || productId.isEmpty()) {
                continue;
            }
            if (delete) {
                indexService.delete(productId);
            } else {
                indexService.upsert(fromCanalRow(row, productId));
            }
            touched.add(productId);
        }
        if (!touched.isEmpty()) {
            log.info("canal 商品索引同步 type={} rows={}", type, touched.size());
            // 缓存失效兜底：binlog 变更可能来自任何写路径（含直接改库），统一失效
            touched.forEach(cacheService::invalidate);
        }
    }

    /** canal flat 行 → ProductInfo 快照（仅索引文档所需字段）。 */
    public static ProductInfo fromCanalRow(JsonNode row, String productId) {
        ProductInfo product = new ProductInfo();
        product.setProductId(productId);
        product.setProductName(row.path("product_name").asText(null));
        product.setProductDesc(row.path("product_desc").asText(null));
        product.setCover(row.path("cover").asText(null));
        product.setBrand(row.path("brand").asText(null));
        product.setCategoryId(row.path("category_id").asText(null));
        product.setpCategoryId(row.path("p_category_id").asText(null));
        product.setStatus(row.path("status").asInt(0));
        product.setMinPrice(decimal(row.path("min_price")));
        product.setMaxPrice(decimal(row.path("max_price")));
        product.setTotalSale(row.path("total_sale").asInt(0));
        product.setCommendType(row.path("commend_type").asInt(0));
        product.setCatalogScope(row.path("catalog_scope").asText(null));
        product.setCreateTime(date(row.path("create_time")));
        return product;
    }

    static BigDecimal decimal(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        try {
            return new BigDecimal(node.asText());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    static Date date(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        if (node.isNumber()) {
            return new Date(node.asLong());
        }
        String text = node.asText();
        if (text.isEmpty()) {
            return null;
        }
        // canal 的 Date 序列化形如 2026-10-06 12:00:00（本地时区）
        for (String pattern : new String[]{"yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss"}) {
            try {
                return new SimpleDateFormat(pattern).parse(text);
            } catch (ParseException ignored) {
                // 尝试下一种格式
            }
        }
        return null;
    }
}
