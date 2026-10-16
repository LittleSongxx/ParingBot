package com.smartlect.controller.internal;

import com.smartlect.catalog.IsolatedCatalog;
import com.smartlect.controller.ABaseController;
import com.smartlect.constants.Constants;
import com.smartlect.api.enums.ProductStatusEnum;
import com.smartlect.api.support.StockRpcSupport;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.po.ProductPropertyValue;
import com.smartlect.entity.po.ProductSku;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.ProductPropertyValueQuery;
import com.smartlect.entity.query.ProductSkuQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.dto.SkuStockQueryDTO;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.mappers.ProductPropertyValueMapper;
import com.smartlect.mappers.ProductSkuMapper;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.PageUtils;
import com.smartlect.utils.ProductContentJson;
import com.smartlect.utils.ProductIndexTextSanitizer;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/internal/product/commerce")
public class ProductCommerceInternalController extends ABaseController {

    @Resource
    private ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper;
    @Resource
    private ProductSkuMapper<ProductSku, ProductSkuQuery> productSkuMapper;
    @Resource
    private ProductPropertyValueMapper<ProductPropertyValue, ProductPropertyValueQuery> productPropertyValueMapper;
    @Resource
    private StockRpcSupport stockRpcSupport;
    @Resource
    private AppConfig appConfig;
    @Resource
    private com.smartlect.search.ProductIndexService productIndexService;

    @PostMapping("/searchOnSale")
    public ResponseVO<List<Map<String, Object>>> searchOnSale(@RequestBody Map<String, Object> body) {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setProductIdList(productIds(body, "productIds"));
        query.setExcludeProductIdList(productIds(body, "excludeProductIds"));
        if (query.getProductIdList() != null && query.getProductIdList().isEmpty()) {
            return getSuccessResponseVO(List.of());
        }
        query.setStatus(ProductStatusEnum.ON_SALE.getStatus());
        // 文本检索谓词优先走 ES 商品索引（与 LIKE 等价的短语包含语义）；
        // 指定 productIds 的定向查询与 ES 不可达（null）时回退 SQL LIKE——
        // 检索永不因索引故障中断。
        String keyword = str(body, "keyword");
        boolean keywordSearch = !StringTools.isEmpty(keyword) && !keyword.startsWith("category:");
        boolean resolvedByIndex = false;
        if (keywordSearch && query.getProductIdList() == null) {
            java.util.List<String> indexIds = productIndexService.searchIdsByKeyword(
                    keyword, query.getExcludeProductIdList(),
                    com.smartlect.search.ProductIndexService.SEARCH_ID_CAP);
            if (indexIds != null) {
                if (indexIds.isEmpty()) {
                    return getSuccessResponseVO(List.of());
                }
                query.setProductIdList(indexIds);
                resolvedByIndex = true;
            }
        }
        if (keywordSearch && !resolvedByIndex) {
            query.setProductNameFuzzy(keyword);
        }
        String categoryId = str(body, "categoryId");
        if (StringTools.isEmpty(categoryId) && keyword != null && keyword.startsWith("category:")) {
            categoryId = keyword.substring("category:".length()).trim();
        }
        if (!StringTools.isEmpty(categoryId)) {
            query.setCategoryId(categoryId);
        }
        java.math.BigDecimal priceFrom = yuanFromCents(body.get("minPriceCents"));
        if (priceFrom != null && priceFrom.compareTo(java.math.BigDecimal.ZERO) > 0) {
            query.setPriceFrom(priceFrom);
        }
        java.math.BigDecimal priceTo = yuanFromCents(body.get("maxPriceCents"));
        if (priceTo != null) {
            query.setPriceTo(priceTo);
        }
        boolean hotSale = Boolean.TRUE.equals(body.get("hotSale"))
                || "true".equalsIgnoreCase(String.valueOf(body.get("hotSale")));
        // Column is total_sale (not sales); mapper aliases table as p.
        if (hotSale) {
            query.setOrderBy(com.smartlect.entity.query.SafeSort.of("p.total_sale desc"));
        } else {
            query.setOrderBy(com.smartlect.entity.query.SafeSort.of("p.create_time desc"));
        }
        int limit = intVal(body.get("limit"), 20);
        if (limit < 1) {
            limit = 1;
        }
        if (limit > 50) {
            limit = 50;
        }
        if (query.getProductIdList() == null) {
            query.setExcludeIsolatedCatalog(true);
        }
        List<ProductInfo> list = PageUtils.pageInfo(1, limit,
                () -> productInfoMapper.selectList(query)).getList();
        Map<String, String> brandByProduct = new HashMap<>();
        Map<String, Integer> stockByProduct = Collections.emptyMap();
        if (list != null && !list.isEmpty()) {
            List<String> productIds = new ArrayList<>();
            for (ProductInfo p : list) {
                productIds.add(p.getProductId());
            }
            stockByProduct = stockRpcSupport.totalByProducts(productIds);
            ProductPropertyValueQuery propertyQuery = new ProductPropertyValueQuery();
            propertyQuery.setProductIdList(productIds);
            List<ProductPropertyValue> properties = productPropertyValueMapper.selectList(propertyQuery);
            if (properties != null) {
                for (ProductPropertyValue property : properties) {
                    if (!brandByProduct.containsKey(property.getProductId())
                            && property.getPropertyName() != null
                            && property.getPropertyName().contains("品牌")
                            && !StringTools.isEmpty(property.getPropertyValue())) {
                        brandByProduct.put(property.getProductId(), property.getPropertyValue());
                    }
                }
            }
        }
        List<Map<String, Object>> result = new ArrayList<>();
        if (list != null) {
            for (ProductInfo p : list) {
                Map<String, Object> card = toProductCard(p);
                String brand = brandByProduct.get(p.getProductId());
                if (!StringTools.isEmpty(brand)) {
                    card.put("brand", brand);
                }
                if (stockByProduct.containsKey(p.getProductId())) {
                    Integer totalStock = stockByProduct.get(p.getProductId());
                    card.put("totalStock", totalStock);
                    card.put("inStock", totalStock != null && totalStock > 0);
                }
                result.add(card);
            }
        }
        return getSuccessResponseVO(result);
    }

    @PostMapping("/getDetail")
    public ResponseVO<Map<String, Object>> getDetail(@RequestBody Map<String, Object> body) {
        String productId = str(body, "productId");
        if (StringTools.isEmpty(productId)) {
            return getSuccessResponseVO(null);
        }
        ProductInfo p = productInfoMapper.selectByProductId(productId);
        if (p == null) {
            return getSuccessResponseVO(null);
        }
        // Same assembling path as the batch variant, so the two shapes cannot drift apart.
        List<Map<String, Object>> details = buildDetails(List.of(p));
        return getSuccessResponseVO(details.isEmpty() ? null : details.get(0));
    }

    /**
     * Batch variant of getDetail for the assistant-side knowledge import: one call per import
     * batch instead of one HTTP round-trip per product. Same sanitized fields and shape as
     * getDetail; products that do not exist are simply absent from the list.
     */
    @PostMapping("/batchDetail")
    public ResponseVO<List<Map<String, Object>>> batchDetail(@RequestBody Map<String, Object> body) {
        List<String> productIds = productIds(body, "productIds");
        if (productIds == null || productIds.isEmpty()) {
            return getSuccessResponseVO(List.of());
        }
        if (productIds.size() > 50) {
            throw new BusinessException("批量详情一次最多 50 个商品");
        }
        ProductInfoQuery query = new ProductInfoQuery();
        query.setProductIdList(productIds);
        List<ProductInfo> products = productInfoMapper.selectList(query);
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> detail : buildDetails(products)) {
            result.add(detail);
        }
        return getSuccessResponseVO(result);
    }

    /**
     * Detail payloads for one or more products with three bulk lookups instead of three per
     * product: the batch endpoint exists to avoid per-product round trips, and a per-product
     * stock RPC call would have reintroduced them.
     */
    private List<Map<String, Object>> buildDetails(List<ProductInfo> products) {
        List<Map<String, Object>> result = new ArrayList<>();
        if (products == null || products.isEmpty()) {
            return result;
        }
        List<String> ids = new ArrayList<>();
        for (ProductInfo p : products) {
            if (p != null) {
                ids.add(p.getProductId());
            }
        }
        Map<String, Integer> stockByProduct = ids.isEmpty() ? Collections.emptyMap() : stockRpcSupport.totalByProducts(ids);

        Map<String, List<ProductSku>> skusByProduct = new HashMap<>();
        Map<String, List<ProductPropertyValue>> propertiesByProduct = new HashMap<>();
        if (!ids.isEmpty()) {
            ProductSkuQuery skuQuery = new ProductSkuQuery();
            skuQuery.setProductIdList(ids);
            skuQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("product_id asc, sort asc"));
            for (ProductSku sku : orEmpty(productSkuMapper.selectList(skuQuery))) {
                skusByProduct.computeIfAbsent(sku.getProductId(), key -> new ArrayList<>()).add(sku);
            }
            ProductPropertyValueQuery pvQuery = new ProductPropertyValueQuery();
            pvQuery.setProductIdList(ids);
            for (ProductPropertyValue property : orEmpty(productPropertyValueMapper.selectList(pvQuery))) {
                propertiesByProduct.computeIfAbsent(property.getProductId(), key -> new ArrayList<>()).add(property);
            }
        }

        for (ProductInfo p : products) {
            if (p == null) {
                continue;
            }
            String productId = p.getProductId();
            Map<String, Object> m = toProductCard(p);
            m.put("status", p.getStatus());
            m.put("maxPrice", p.getMaxPrice());
            String searchableDescription = ProductIndexTextSanitizer.sanitize(p.getProductDesc());
            m.put("description", searchableDescription);
            m.put("productDesc", searchableDescription);
            m.put("content", ProductContentJson.toContentMap(p.getContentJson(), p.getProductDesc()));
            List<ProductSku> skus = skusByProduct.get(productId);
            m.put("skus", skus == null ? Collections.emptyList() : skus);
            List<ProductPropertyValue> pvs = propertiesByProduct.get(productId);
            m.put("propertyValues", pvs == null ? Collections.emptyList() : pvs);
            String propertyBrand = null;
            if (pvs != null) {
                for (ProductPropertyValue property : pvs) {
                    if (property.getPropertyName() != null
                            && property.getPropertyName().contains("品牌")
                            && !StringTools.isEmpty(property.getPropertyValue())) {
                        propertyBrand = property.getPropertyValue();
                        break;
                    }
                }
            }
            String brand = ProductContentJson.firstBrand(p.getBrand(), propertyBrand);
            if (!StringTools.isEmpty(brand)) {
                m.put("brand", brand);
            }
            if (stockByProduct.containsKey(productId)) {
                Integer totalStock = stockByProduct.get(productId);
                m.put("totalStock", totalStock);
                m.put("inStock", totalStock != null && totalStock > 0);
            }
            result.add(m);
        }
        return result;
    }

    private static <T> List<T> orEmpty(List<T> list) {
        return list == null ? Collections.emptyList() : list;
    }

    /**
     * Authoritative SKU offer facts for the assistant service.  This endpoint deliberately
     * returns a selected in-stock SKU and its base price; user coupons are
     * estimated by the Coupon service in a separate internal call.  The assistant service
     * never reads product or stock tables directly.
     */
    @PostMapping("/offerSnapshots")
    public ResponseVO<Map<String, Object>> offerSnapshots(@RequestBody Map<String, Object> body) {
        Object rawIds = body == null ? null : body.get("productIds");
        if (!(rawIds instanceof List<?> ids) || ids.isEmpty()) {
            return getSuccessResponseVO(Map.of("products", List.of()));
        }
        Map<String, Set<String>> allowedSkuKeysByProduct = parseAllowedSkuKeys(
                body.get("allowedSkuKeysByProduct"));

        List<Map<String, Object>> result = new ArrayList<>();
        int processed = 0;
        for (Object rawId : ids) {
            if (processed++ >= 20 || rawId == null) {
                break;
            }
            String productId = String.valueOf(rawId).trim();
            if (StringTools.isEmpty(productId)) {
                continue;
            }
            ProductInfo product = productInfoMapper.selectByProductId(productId);
            if (product == null) {
                continue;
            }
            ProductSkuQuery skuQuery = new ProductSkuQuery();
            skuQuery.setProductId(productId);
            skuQuery.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
            List<ProductSku> skus = productSkuMapper.selectList(skuQuery);
            Map<String, Object> row = toProductCard(product);
            row.put("status", product.getStatus());
            row.put("categoryId", product.getCategoryId());
            row.put("cover", product.getCover());
            int totalStock = 0;
            Map<String, Object> selected = null;
            Set<String> allowedSkuKeys = allowedSkuKeysByProduct.get(productId);
            if (skus != null) {
                for (ProductSku sku : skus) {
                    if (sku == null || StringTools.isEmpty(sku.getPropertyValueIdHash())
                            || sku.getPrice() == null) {
                        continue;
                    }
                    if (allowedSkuKeys != null
                            && !allowedSkuKeys.contains(sku.getPropertyValueIdHash())) {
                        continue;
                    }
                    int stock = Math.max(0, stockRpcSupport.getAvailable(
                            productId, sku.getPropertyValueIdHash()));
                    totalStock += stock;
                    if (stock <= 0 || !ProductStatusEnum.ON_SALE.getStatus().equals(product.getStatus())) {
                        continue;
                    }
                    if (selected == null || sku.getPrice().compareTo(
                            (java.math.BigDecimal) selected.get("price")) < 0) {
                        selected = new LinkedHashMap<>();
                        selected.put("propertyValueIdHash", sku.getPropertyValueIdHash());
                        selected.put("propertyValueIds", sku.getPropertyValueIds());
                        selected.put("price", sku.getPrice());
                        selected.put("stock", stock);
                    }
                }
            }
            row.put("totalStock", totalStock);
            row.put("inStock", selected != null);
            row.put("selectedSku", selected);
            result.add(row);
        }
        return getSuccessResponseVO(Map.of("products", result));
    }

    static Map<String, Set<String>> parseAllowedSkuKeys(Object rawAllowed) {
        Map<String, Set<String>> allowedSkuKeysByProduct = new HashMap<>();
        if (rawAllowed instanceof Map<?, ?> allowedMap) {
            for (Map.Entry<?, ?> entry : allowedMap.entrySet()) {
                if (entry.getKey() == null || !(entry.getValue() instanceof List<?> values)) {
                    continue;
                }
                Set<String> keys = values.stream()
                        .filter(value -> value != null
                                && !StringTools.isEmpty(String.valueOf(value).trim()))
                        .map(value -> String.valueOf(value).trim())
                        .collect(Collectors.toSet());
                if (!keys.isEmpty()) {
                    allowedSkuKeysByProduct.put(String.valueOf(entry.getKey()).trim(), keys);
                }
            }
        }
        return allowedSkuKeysByProduct;
    }

    @PostMapping("/imageContent")
    public void imageContent(@RequestBody Map<String, Object> body, HttpServletResponse response)
            throws IOException {
        String productId = str(body, "productId");
        int coverIndex = intVal(body == null ? null : body.get("coverIndex"), 0);
        if (StringTools.isEmpty(productId) || coverIndex < 0 || coverIndex >= 5) {
            throw new BusinessException("商品图片参数不合法");
        }
        ProductInfo product = productInfoMapper.selectByProductId(productId);
        if (product == null || StringTools.isEmpty(product.getCover())) {
            throw new BusinessException("商品图片不存在");
        }
        List<String> covers = Arrays.stream(product.getCover().split(","))
                .map(String::trim)
                .filter(value -> !StringTools.isEmpty(value))
                .limit(5)
                .toList();
        if (coverIndex >= covers.size()) {
            throw new BusinessException("商品图片不存在");
        }
        String sourceName = covers.get(coverIndex);
        if (!StringTools.pathIsOK(sourceName)) {
            throw new BusinessException("商品图片路径不合法");
        }

        File baseFolder = new File(
                appConfig.getProjectFolder() + Constants.FILE_FOLDER_FILE).getCanonicalFile();
        File image = new File(baseFolder, sourceName).getCanonicalFile();
        if (!image.toPath().startsWith(baseFolder.toPath())
                || !image.isFile() || image.length() <= 0 || image.length() > 20L * 1024 * 1024) {
            throw new BusinessException("商品图片不可读取");
        }
        response.setContentType(resolveImageContentType(sourceName));
        response.setHeader("Cache-Control", "private, max-age=300");
        response.setHeader("X-Content-Type-Options", "nosniff");
        response.setContentLengthLong(image.length());
        try (FileInputStream input = new FileInputStream(image);
             OutputStream output = response.getOutputStream()) {
            input.transferTo(output);
        }
    }

    /** 增长服务商品卡片的唯一销量字段。 */
    private static Map<String, Object> toProductCard(ProductInfo p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("productId", p.getProductId());
        m.put("productName", p.getProductName());
        m.put("cover", p.getCover());
        m.put("status", p.getStatus());
        m.put("minPrice", p.getMinPrice());
        m.put("maxPrice", p.getMaxPrice());
        m.put("categoryId", p.getCategoryId());
        m.put("totalSale", p.getTotalSale());
        m.put("commendType", p.getCommendType());
        m.put("catalogScope", p.getCatalogScope() == null ? IsolatedCatalog.SCOPE_STORE : p.getCatalogScope());
        return m;
    }

    private static List<String> productIds(Map<String, Object> body, String key) {
        if (body == null || !body.containsKey(key)) {
            return null;
        }
        if (!(body.get(key) instanceof List<?> values) || values.size() > 5000) {
            throw new BusinessException(400, "invalid_" + key);
        }
        List<String> ids = new ArrayList<>(values.size());
        for (Object value : values) {
            if (!(value instanceof String id) || id.isBlank() || id.length() > 64 || id.indexOf('\0') >= 0) {
                throw new BusinessException(400, "invalid_" + key);
            }
            ids.add(id);
        }
        return ids;
    }

    private static String str(Map<String, Object> body, String key) {
        if (body == null || body.get(key) == null) {
            return null;
        }
        String v = String.valueOf(body.get(key));
        return "null".equals(v) ? null : v;
    }

    private static java.math.BigDecimal yuanFromCents(Object raw) {
        if (raw == null) {
            return null;
        }
        try {
            long cents = Long.parseLong(String.valueOf(raw).trim());
            if (cents < 0 || cents > 100_000_000L) {
                return null;
            }
            return java.math.BigDecimal.valueOf(cents, 2);
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static int intVal(Object v, int def) {
        if (v == null) {
            return def;
        }
        try {
            return Integer.parseInt(String.valueOf(v));
        } catch (Exception e) {
            return def;
        }
    }

    private static String resolveImageContentType(String sourceName) {
        String normalized = sourceName == null ? "" : sourceName.toLowerCase();
        if (normalized.endsWith(".png")) {
            return "image/png";
        }
        if (normalized.endsWith(".webp")) {
            return "image/webp";
        }
        if (normalized.endsWith(".gif")) {
            return "image/gif";
        }
        if (normalized.endsWith(".bmp")) {
            return "image/bmp";
        }
        return "image/jpeg";
    }
}
