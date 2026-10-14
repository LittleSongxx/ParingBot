package com.smartlect.utils;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** 分页上限（ADR-0021）：pageSize 传入超上限值被收敛，正常值不受影响。 */
class PageUtilsCapTest {

    @Test
    void capsOversizedPageSizeButKeepsNormalValues() {
        assertEquals(100, PageUtils.capPageSize(10000));
        assertEquals(15, PageUtils.capPageSize(15));
        assertEquals(1, PageUtils.capPageSize(1));
    }
}
