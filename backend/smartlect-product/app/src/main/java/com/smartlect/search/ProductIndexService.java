package com.smartlect.search;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.SortOrder;
import co.elastic.clients.elasticsearch._types.query_dsl.Query;
import co.elastic.clients.elasticsearch.core.BulkRequest;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import co.elastic.clients.elasticsearch.core.CountResponse;
import co.elastic.clients.elasticsearch.core.DeleteRequest;
import co.elastic.clients.elasticsearch.core.IndexRequest;
import co.elastic.clients.elasticsearch.core.SearchRequest;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import co.elastic.clients.elasticsearch.indices.CreateIndexRequest;
import co.elastic.clients.elasticsearch.indices.ExistsRequest;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.entity.query.ProductInfoQuery;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 商品搜索索引（smartlect-products）的读写门面。
 *
 * <p>索引只承担检索谓词（文本短语包含 + 在售过滤），结构化过滤（品类、价格区间、
 * 排除项）与排序仍由 DB 查询完成——文本谓词的**默认**语义必须与被替换的
 * {@code product_name like '%kw%'} 逐字等价：keyword 子字段 + case-insensitive
 * wildcard（v16 评测曾因分词检索放宽资格语义而回退，见 ProductInfoMapper 注释）。</p>
 *
 * <p><b>打分腿（hybrid 模式）默认关闭，有实测依据</b>（{@code scripts/eval_product_search.py}，
 * 2026-10-16 / 87469 条索引 / 40 采样 / top-10）：分词腿把命中集合从个位数放大到数百条
 * （同查询 wildcard 1 条 vs match 210 条），而本索引返回的是**按创建时间排序的 top-N**——
 * 宽松命中会把逐字命中的那一条顶出窗口：实测逐字查询命中率 100% → 68%，词序打乱查询
 * 12% → 44%，同时前 10 条里多出 15 条不逐字包含的结果。也就是说"保留子串腿 = 召回超集"
 * 只对无界结果集成立，对"有界窗口 + 非分数排序"不成立。要用分数换相关性，得把排序权
 * 整体交给 ES（分页/过滤契约要重做），那是另一档重构。可设
 * {@code smartlect.search.mode=hybrid} 复现这组对照。</p>
 *
 * <p>价格/库存不入索引（与"交易事实以 Java 查询时点为准"的架构边界一致），
 * 仅冗余商品静态快照。ES 不可达时所有方法返回降级信号（null / false），
 * 调用方回退 SQL LIKE。</p>
 */
@Slf4j
@Service
public class ProductIndexService {

    public static final String INDEX = "smartlect-products";
    /** ES 检索命中的 id 上限：约束单次回表批量，DB 侧分页在其子集上进行。 */
    public static final int SEARCH_ID_CAP = 500;

    /**
     * 建索引 mapping：productName 双字段（IK 文本快照 + raw keyword 供短语 wildcard）。
     * text 字段仅冗余商品快照、当前不参与检索谓词；检索语义始终由 raw keyword 的
     * wildcard 保证（与 SQL LIKE 逐字等价）。
     */

    /** 检索谓词模式：substring = 与 SQL LIKE 逐字等价（默认）；hybrid = 叠加分词打分腿。 */
    static final String MODE_SUBSTRING = "substring";
    static final String MODE_HYBRID = "hybrid";

    private final ElasticsearchClient client;
    private final ProductInfoMapper productInfoMapper;

    @Value("${smartlect.search.mode:substring}")
    private String searchMode = MODE_SUBSTRING;

    public ProductIndexService(ElasticsearchClient client, ProductInfoMapper productInfoMapper) {
        this.client = client;
        this.productInfoMapper = productInfoMapper;
    }

    /** 供测试与运维核对当前生效模式（非法值等价于默认）。 */
    String searchMode() {
        return MODE_HYBRID.equals(searchMode) ? MODE_HYBRID : MODE_SUBSTRING;
    }

    public boolean ensureIndex() {
        try {
            boolean exists = client.indices()
                    .exists(ExistsRequest.of(b -> b.index(INDEX))).value();
            if (!exists) {
                boolean created = tryCreateIndex("ik_max_word");
                if (!created) {
                    // IK 插件缺失时（unknown analyzer 400）降级重建：text 字段仅冗余
                    // 快照不参与检索，分词器缺失不影响 wildcard 检索语义。
                    tryCreateIndex(null);
                    log.warn("商品索引 {} 已创建（未装 IK 插件，text 快照走 standard 分词；检索谓词不受影响）", INDEX);
                }
            }
            return true;
        } catch (IOException e) {
            log.warn("商品索引 ensure 失败（ES 不可达将回退 SQL）：{}", e.getMessage());
            return false;
        }
    }

    /**
     * 用指定 analyzer（null 表示不指定）创建索引；IK 缺失返回 false 由调用方降级，
     * 索引已存在视为成功（并发/重复初始化）。
     */
    private boolean tryCreateIndex(String analyzer) {
        try {
            String effective = analyzer != null ? analyzer : "standard";
            // 显式 Java API 构建 mapping（withJson 会被动态映射覆盖）
            client.indices().create(c -> c
                    .index(INDEX)
                    .settings(se -> se
                            .analysis(a -> a
                                    .analyzer("zh_text", an -> an
                                            .custom(z -> z
                                                    .tokenizer(effective))))  )
                    .mappings(m -> m
                            .properties("productId", p -> p.keyword(k -> k))
                            .properties("productName", p -> p.text(t -> t
                                    .analyzer("zh_text")
                                    .fields("raw", f -> f.keyword(k -> k))))
                            .properties("productDesc", p -> p.text(t -> t.analyzer("zh_text")))
                            .properties("brand", p -> p.keyword(k -> k))
                            .properties("categoryId", p -> p.keyword(k -> k))
                            .properties("pCategoryId", p -> p.keyword(k -> k))
                            .properties("cover", p -> p.keyword(k -> k.index(false).docValues(false)))
                            .properties("status", p -> p.integer(i -> i))
                            .properties("minPriceCents", p -> p.long_(l -> l))
                            .properties("maxPriceCents", p -> p.long_(l -> l))
                            .properties("totalSale", p -> p.integer(i -> i))
                            .properties("commendType", p -> p.integer(i -> i))
                            .properties("catalogScope", p -> p.keyword(k -> k))
                            .properties("createTimeMillis", p -> p.long_(l -> l))));
            if (analyzer != null) {
                log.info("商品索引 {} 已创建（{} 分词快照与 raw keyword 子字段）", INDEX, analyzer);
            }
            return true;
        } catch (co.elastic.clients.elasticsearch._types.ElasticsearchException e) {
            if ("resource_already_exists_exception".equals(e.error().type())) {
                return true;
            }
            // 未装 IK 插件时引用 ik_max_word tokenizer 建索引 400（Unknown xxx）
            if (analyzer != null && e.getMessage() != null
                    && e.getMessage().contains("nknown")
                    && e.getMessage().contains(analyzer)) {
                return false;
            }
            throw e;
        } catch (IOException io) {
            throw new java.io.UncheckedIOException(io);
        }
    }

    public boolean upsert(ProductInfo product) {
        try {
            client.index(IndexRequest.of(b -> b.index(INDEX)
                    .id(product.getProductId()).document(toDocument(product))));
            return true;
        } catch (IOException e) {
            log.warn("商品索引写入失败 productId={}：{}", product.getProductId(), e.getMessage());
            return false;
        }
    }

    public boolean delete(String productId) {
        try {
            client.delete(DeleteRequest.of(b -> b.index(INDEX).id(productId)));
            return true;
        } catch (IOException e) {
            log.warn("商品索引删除失败 productId={}：{}", productId, e.getMessage());
            return false;
        }
    }

    public long count() {
        try {
            CountResponse response = client.count(b -> b.index(INDEX));
            return response.count();
        } catch (IOException e) {
            return -1;
        }
    }

    /** 全量重建（幂等 upsert，不清索引）：初始化器在索引为空时调用。 */
    public int rebuildAll(int pageSize) {
        if (!ensureIndex()) {
            return -1;
        }
        int effectiveSize = Math.max(1, pageSize);
        int total = 0;
        int batchNo = 1;
        String lastId = null;
        while (true) {
            // keyset 翻页：不能复用 PageUtils，否则单页会被压到 100，
            // 且总页数被 500 页上限截断，历史商品永远重建不到。
            List<ProductInfo> page = productInfoMapper.selectForIndex(lastId, effectiveSize);
            if (page == null || page.isEmpty()) {
                break;
            }
            BulkRequest.Builder bulk = new BulkRequest.Builder();
            for (ProductInfo product : page) {
                Map<String, Object> doc = toDocument(product);
                bulk.operations(op -> op.index(idx -> idx.index(INDEX)
                        .id(product.getProductId()).document(doc)));
            }
            try {
                BulkResponse response = client.bulk(bulk.build());
                if (response.errors()) {
                    log.warn("全量索引第 {} 批存在失败项", batchNo);
                }
            } catch (IOException e) {
                log.warn("全量索引第 {} 批失败：{}", batchNo, e.getMessage());
            }
            total += page.size();
            lastId = page.get(page.size() - 1).getProductId();
            if (lastId == null || page.size() < effectiveSize) {
                break;
            }
            batchNo++;
        }
        log.info("商品索引全量重建完成：{} 条", total);
        return total;
    }

    /**
     * 文本检索谓词：与 {@code product_name like '%kw%'} 逐字等价的短语包含
     * （keyword 子字段 + case-insensitive wildcard），叠加在售与目录隔离过滤。
     *
     * @return 有序 productId 列表（create_time desc，对齐 DB 默认排序）；
     *         {@code null} 表示 ES 不可达，调用方应回退 SQL LIKE
     */
    public List<String> searchIdsByKeyword(String keyword, Collection<String> excludeProductIds, int limit) {
        String trimmed = keyword == null ? "" : keyword.trim();
        if (trimmed.isEmpty()) {
            return List.of();
        }
        int capped = Math.min(Math.max(limit, 1), SEARCH_ID_CAP);
        List<String> exclude = excludeProductIds == null ? List.of()
                : excludeProductIds.stream().limit(1000).toList();
        try {
            String pattern = "*" + escapeWildcard(trimmed) + "*";
            List<co.elastic.clients.elasticsearch._types.FieldValue> excludeValues = exclude.stream()
                    .map(co.elastic.clients.elasticsearch._types.FieldValue::of).toList();
            Query query = Query.of(q -> {
                q.bool(b -> {
                    // 文本谓词：substring 与 LIKE 等价；hybrid 在保留子串腿的前提下叠加分词腿
                    // （minimumShouldMatch=1 → 召回是子串的超集，评测脚本量化放宽了多少）
                    b.must(m -> m.bool(t -> {
                        t.should(sh -> sh.wildcard(w -> w
                                .field("productName.raw").caseInsensitive(true).wildcard(pattern)
                                .boost(1.0f)));
                        if (MODE_HYBRID.equals(searchMode())) {
                            t.should(sh -> sh.match(mq -> mq.field("productName").query(trimmed).boost(2.0f)));
                            t.should(sh -> sh.match(mq -> mq.field("productDesc").query(trimmed).boost(1.0f)));
                        }
                        t.minimumShouldMatch("1");
                        return t;
                    }));
                    b.filter(f -> f.term(t -> t.field("status").value(1)));
                    b.filter(f -> f.bool(nb -> nb
                            .mustNot(n -> n.term(t -> t.field("catalogScope").value("eval")))));
                    if (!excludeValues.isEmpty()) {
                        b.filter(f -> f.bool(nb -> nb.mustNot(n -> n.terms(t -> t
                                .field("productId").terms(tv -> tv.value(excludeValues))))));
                    }
                    return b;
                });
                return q;
            });
            SearchResponse<Map> response = client.search(SearchRequest.of(b -> b
                    .index(INDEX).query(query)
                    .size(capped)
                    .sort(s -> s.field(f -> f.field("createTimeMillis").order(SortOrder.Desc)))),
                    Map.class);
            List<String> ids = new ArrayList<>();
            for (Hit<Map> hit : response.hits().hits()) {
                if (hit.id() != null) {
                    ids.add(hit.id());
                }
            }
            return ids;
        } catch (IOException e) {
            log.warn("商品索引检索失败（回退 SQL LIKE）：{}", e.getMessage());
            return null;
        }
    }

    /** wildcard 元字符转义：保持与 LIKE 字面量一致的"用户输入即字面"语义。 */
    static String escapeWildcard(String input) {
        return input.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?");
    }

    static Map<String, Object> toDocument(ProductInfo p) {
        Map<String, Object> doc = new HashMap<>();
        doc.put("productId", p.getProductId());
        doc.put("productName", p.getProductName());
        doc.put("productDesc", p.getProductDesc());
        doc.put("brand", p.getBrand());
        doc.put("categoryId", p.getCategoryId());
        doc.put("pCategoryId", p.getpCategoryId());
        doc.put("cover", p.getCover());
        doc.put("status", p.getStatus());
        doc.put("minPriceCents", cents(p.getMinPrice()));
        doc.put("maxPriceCents", cents(p.getMaxPrice()));
        doc.put("totalSale", p.getTotalSale() == null ? 0 : p.getTotalSale());
        doc.put("commendType", p.getCommendType() == null ? 0 : p.getCommendType());
        doc.put("catalogScope", p.getCatalogScope() == null ? "store" : p.getCatalogScope());
        doc.put("createTimeMillis", p.getCreateTime() == null ? 0L : p.getCreateTime().getTime());
        return doc;
    }

    static long cents(BigDecimal yuan) {
        return yuan == null ? 0L : yuan.movePointRight(2).longValue();
    }
}
