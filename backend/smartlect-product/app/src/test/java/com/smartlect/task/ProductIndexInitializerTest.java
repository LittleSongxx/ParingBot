package com.smartlect.task;

import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import com.smartlect.entity.po.ProductInfo;
import com.smartlect.entity.query.ProductInfoQuery;
import com.smartlect.mappers.ProductInfoMapper;
import com.smartlect.search.ProductIndexService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 启动重建的判据：缺文档才重建；索引非空且不缺文档就跳过。
 * 这样既避免每次重启全量 upsert 87k，又保留 Canal 停摆后的自愈路径。
 */
@ExtendWith(MockitoExtension.class)
class ProductIndexInitializerTest {

    @Mock
    private ProductIndexService indexService;
    @Mock
    private ProductInfoMapper<ProductInfo, ProductInfoQuery> productInfoMapper;

    private ProductIndexInitializer initializer;

    @BeforeEach
    void setUp() {
        initializer = new ProductIndexInitializer(indexService, productInfoMapper);
        ReflectionTestUtils.setField(initializer, "forceRebuild", false);
    }

    @AfterEach
    void clearPageHelper() {
        PageHelper.clearPage();
    }

    @Test
    void skipsEverythingWhenElasticsearchIsUnreachable() {
        when(indexService.ensureIndex()).thenReturn(false);

        initializer.initializeIndex();

        verify(indexService, never()).rebuildAll(500);
    }

    @Test
    void rebuildsWhenIndexIsEmpty() {
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(0L);

        initializer.initializeIndex();

        verify(indexService).rebuildAll(500);
    }

    @Test
    void rebuildsWhenIndexIsMissingDocuments() {
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(10L);
        stubDbCount(100);

        initializer.initializeIndex();

        verify(indexService).rebuildAll(500);
    }

    @Test
    void rebuildsWhenDocumentCountIsUnknown() {
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(-1L);

        initializer.initializeIndex();

        verify(indexService).rebuildAll(500);
    }

    @Test
    void skipsWhenIndexCoversAllProducts() {
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(100L);
        stubDbCount(100);

        initializer.initializeIndex();

        verify(indexService, never()).rebuildAll(500);
    }

    @Test
    void skipsWhenIndexHasExtraDocuments() {
        // 多余文档（Canal 漏了删除）会被 status 过滤挡住；不为它每次重启全量重建
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(120L);
        stubDbCount(100);

        initializer.initializeIndex();

        verify(indexService, never()).rebuildAll(500);
    }

    @Test
    void forceRebuildWinsOverCountChecks() {
        ReflectionTestUtils.setField(initializer, "forceRebuild", true);
        when(indexService.ensureIndex()).thenReturn(true);
        when(indexService.count()).thenReturn(100L);

        initializer.initializeIndex();

        verify(indexService).rebuildAll(500);
        verify(productInfoMapper, never()).selectList(any());
    }

    private void stubDbCount(long total) {
        Page<ProductInfo> page = new Page<>(1, 15);
        page.setTotal(total);
        page.addAll(List.of(new ProductInfo()));
        when(productInfoMapper.selectList(any(ProductInfoQuery.class))).thenReturn(page);
    }
}
