package com.smartlect.biz.impl;

import com.smartlect.api.support.ProductRpcSupport;
import com.smartlect.entity.po.ProductCart;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ProductCartMapper;
import com.smartlect.entity.query.ProductCartQuery;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 批次七补弱模块：cart 核心加购语义（此前模块仅 1 个 29 行 surface 测试）。 */
@ExtendWith(MockitoExtension.class)
class ProductCartServiceTest {

    @Mock
    private ProductCartMapper<ProductCart, ProductCartQuery> productCartMapper;
    @Mock
    private ProductRpcSupport productRpcSupport;

    @InjectMocks
    private ProductCartServiceImpl service;

    @BeforeEach
    void lenientSnapshot() {
        lenient().when(productRpcSupport.snapshotBatch(any())).thenReturn(null);
    }

    private static ProductCart cart(String userId, String productId, String propertyValueIds, Integer buyCount) {
        ProductCart cart = new ProductCart();
        cart.setUserId(userId);
        cart.setProductId(productId);
        cart.setPropertyValueIds(propertyValueIds);
        cart.setBuyCount(buyCount);
        return cart;
    }

    @Test
    void existingLineMergesQuantityWithoutTouchingAddPrice() {
        ProductCart existing = cart("u1", "p1", "101-202", 2);
        existing.setAddPrice(new BigDecimal("9.90"));
        when(productCartMapper.selectByProductIdAndPropertyValueIdHashAndUserId(
                eq("p1"), anyString(), eq("u1"))).thenReturn(existing);
        lenient().when(productRpcSupport.toSkuMapByPropertyValueIds(any())).thenReturn(java.util.Map.of());

        service.add2Cart(cart("u1", "p1", "101-202", 3));

        // 合并数量 + 更新 lastUpdateTime，且清空 buyCount/addPrice 字段避免覆盖首次加购价
        verify(productCartMapper).setBuyCountByProductIdAndPropertyValueIdHashAndUserId(
                eq(3), eq("p1"), anyString(), eq("u1"));
        verify(productCartMapper, never()).insert(any(ProductCart.class));
    }

    @Test
    void overLimitQuantityIsRejected() {
        when(productCartMapper.selectByProductIdAndPropertyValueIdHashAndUserId(
                eq("p1"), anyString(), eq("u1"))).thenReturn(null);

        assertThrows(BusinessException.class,
                () -> service.add2Cart(cart("u1", "p1", "101-202", 100)));
        verify(productCartMapper, never()).insert(any(ProductCart.class));
    }

    @Test
    void invalidQuantityIsRejectedBeforeAnyWrite() {
        assertThrows(BusinessException.class,
                () -> service.add2Cart(cart("u1", "p1", "101-202", 0)));
        verify(productCartMapper, never()).setBuyCountByProductIdAndPropertyValueIdHashAndUserId(
                org.mockito.ArgumentMatchers.anyInt(), anyString(), anyString(), anyString());
    }
}
