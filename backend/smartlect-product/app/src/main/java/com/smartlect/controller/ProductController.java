package com.smartlect.controller;

import com.smartlect.entity.enums.ProductSortKey;
import com.smartlect.entity.enums.SortDirection;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.entity.query.SysCategoryQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.Product4VO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.ProductInfoService;
import com.smartlect.biz.SysCategoryService;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

@RestController
@RequestMapping("/product")
@Validated
public class ProductController extends ABaseController {

    @Resource
    private SysCategoryService sysCategoryService;

    @Resource
    private ProductInfoService productInfoService;
    @Resource
    private com.smartlect.search.ProductIndexService productIndexService;

    @GetMapping("/loadCategory")
    public ResponseVO loadCategory() {
        SysCategoryQuery query = new SysCategoryQuery();
        query.setParent(true);
        query.setPropertyQuery(true);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("sort asc"));
        return getSuccessResponseVO(sysCategoryService.findListByParam(query));
    }

    @GetMapping("/loadCommendProduct")
    public ResponseVO loadCommendProduct() {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setCommendType(1);
        query.setStatus(1);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("create_time desc"));
        query.setPageNo(1);
        query.setPageSize(11);
        query.setExcludeIsolatedCatalog(true);
        return getSuccessResponseVO(productInfoService.findListByPage(query).getList());
    }

    @PostMapping("/loadProduct")
    public ResponseVO loadProduct(@NotNull Integer pageNo,
                                  String categoryId,
                                  @Size(max = 50) String keyword,
                                  BigDecimal priceFrom,
                                  BigDecimal priceTo,
                                  ProductSortKey sortKey,
                                  SortDirection sortDirection,
                                  @Size(max = 120000) String excludeProductIds) {
        ProductInfoQuery query = new ProductInfoQuery();
        query.setPageNo(pageNo);
        query.setStatus(com.smartlect.api.enums.ProductStatusEnum.ON_SALE.getStatus());
        query.setPriceFrom(priceFrom);
        query.setPriceTo(priceTo);
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of(buildProductOrderBy(sortKey, sortDirection)));
        query.setExcludeProductIdList(parseExcludeProductIds(excludeProductIds));
        query.setExcludeIsolatedCatalog(true);
        // 关键词检索走 ES 商品索引（与 LIKE 等价的短语包含语义）；ES 不可达回退 SQL。
        String trimmed = keyword == null ? null : keyword.trim();
        if (trimmed != null && !trimmed.isEmpty()) {
            java.util.List<String> indexIds = productIndexService.searchIdsByKeyword(
                    trimmed, query.getExcludeProductIdList(),
                    com.smartlect.search.ProductIndexService.SEARCH_ID_CAP);
            if (indexIds != null) {
                if (indexIds.isEmpty()) {
                    // 索引明确返回“没有命中”时不能把空 ID 列表交给 Mapper：
                    // <if size>0> 会让 product_id in (...) 整段消失，退化成返回全部在售商品。
                    return getSuccessResponseVO(new PaginationResultVO<>(
                            0, com.smartlect.entity.enums.PageSize.SIZE15.getSize(), pageNo, 0,
                            Collections.emptyList()));
                }
                query.setProductIdList(indexIds);
            } else {
                query.setProductNameFuzzy(trimmed);
            }
        }
        // A keyword searches the whole on-sale catalogue. Restricting to commended products
        // only makes sense for the default landing list, not for a search.
        if (categoryId == null) {
            if (trimmed == null || trimmed.isEmpty()) {
                query.setCommendType(0);
            }
            return getSuccessResponseVO(productInfoService.findListByPage(query));
        }
        query.setCategoryIdOrPCategoryId(categoryId);
        return getSuccessResponseVO(productInfoService.findListByPage(query));
    }

    static List<String> parseExcludeProductIds(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        List<String> ids = new ArrayList<>();
        for (String part : raw.split(",")) {
            String id = part.trim();
            if (id.isEmpty()) {
                continue;
            }
            if (id.length() > 64 || !id.matches("[A-Za-z0-9_-]+")) {
                continue;
            }
            ids.add(id);
            if (ids.size() >= 5000) {
                break;
            }
        }
        return ids.isEmpty() ? null : ids;
    }

    private String buildProductOrderBy(ProductSortKey sortKey, SortDirection sortDirection) {
        if (ProductSortKey.PRICE.equals(sortKey)) {
            return SortDirection.ASC.equals(sortDirection)
                    ? "min_price asc, total_sale desc"
                    : "min_price desc, total_sale desc";
        }
        if (ProductSortKey.SALE.equals(sortKey)) {
            return "total_sale desc, min_price asc";
        }
        return "commend_type desc, total_sale desc, create_time desc";
    }

    @PostMapping("/getProduct")
    public ResponseVO getProduct(@NotNull String productId) {
        Product4VO product = productInfoService.getProduct4VOByProductId(productId, true);
        return getSuccessResponseVO(product);
    }
}
