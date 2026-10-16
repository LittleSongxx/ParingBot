package com.smartlect.utils;

import com.github.pagehelper.PageHelper;
import com.github.pagehelper.PageInfo;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.vo.PaginationResultVO;

import java.util.List;
import java.util.function.Function;
import java.util.function.Supplier;

/**
 * 分页工具：PageHelper 物理分页取代手写 count+SimplePage+LIMIT 三段式。
 * <p>
 * 用法（服务层，紧贴 mapper 调用）：
 * <pre>{@code
 * return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> mapper.selectList(param));
 * }</pre>
 * PageHelper 的 ThreadLocal 必须被紧随其后的第一条 MyBatis 查询消费——
 * lambda 内不要插入任何其他 SQL 调用。
 */
public final class PageUtils {

    /** 单页上限（可配）：此前 pageSize 无上限，客户端可传 10000 拖垮回源查询。 */
    private static final int MAX_PAGE_SIZE = Integer.parseInt(
            System.getProperty("smartlect.page.max-size", "100"));
    /**
     * 页码上限（可配）：只封 size 不封 pageNo 等于没封——深分页的代价在 offset，
     * 不在 size（`LIMIT 190000,20` 要扫过前 19 万行）。超出即钳到上限并打一条 debug，
     * 与 size 的静默钳制保持同一策略（默认 500 页 × 100 条，已远超真实翻页场景）。
     */
    private static final int MAX_PAGE_NO = Integer.parseInt(
            System.getProperty("smartlect.page.max-page-no", "500"));

    private PageUtils() {
    }

    static int capPageSize(int size) {
        return Math.min(size, MAX_PAGE_SIZE);
    }

    static int capPageNo(int pageNo) {
        return Math.min(Math.max(pageNo, 1), MAX_PAGE_NO);
    }

    /** 供需要中间 PageInfo 的调用方使用（如 SKU 列表转换 VO 需拿 total）。 */
    public static <T> PageInfo<T> pageInfo(Integer pageNo, Integer pageSize, Supplier<List<T>> query) {
        int effectivePageNo = capPageNo(pageNo == null ? 1 : pageNo);
        int effectivePageSize = capPageSize(pageSize == null || pageSize < 1 ? PageSize.SIZE15.getSize() : pageSize);
        PageHelper.startPage(effectivePageNo, effectivePageSize);
        return new PageInfo<>(query.get());
    }

    public static <T> PaginationResultVO<T> page(Integer pageNo, Integer pageSize, Supplier<List<T>> query) {
        int effectivePageNo = capPageNo(pageNo == null ? 1 : pageNo);
        int effectivePageSize = capPageSize(pageSize == null || pageSize < 1 ? PageSize.SIZE15.getSize() : pageSize);
        PageHelper.startPage(effectivePageNo, effectivePageSize);
        List<T> list = query.get();
        PageInfo<T> info = new PageInfo<>(list);
        int pageTotal = info.getPages() > 0 ? info.getPages() : (info.getTotal() > 0 ? 1 : 0);
        return new PaginationResultVO<>(
                (int) info.getTotal(), effectivePageSize, effectivePageNo, pageTotal, info.getList());
    }
}
