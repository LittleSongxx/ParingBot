package com.smartlect.biz;

import com.smartlect.api.dto.OrderStockRestoreDTO;
import com.smartlect.api.dto.RefundStockRestoreDTO;
import com.smartlect.api.dto.SkuStockChangeDTO;
import com.smartlect.component.HotSkuStockGate;
import com.smartlect.mappers.SkuStockMapper;
import com.smartlect.mappers.StockChangeRecordMapper;
import com.smartlect.metrics.SmartlectMetrics;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SkuStockServiceTest {

    @Mock
    private SkuStockMapper skuStockMapper;
    @Mock
    private StockChangeRecordMapper stockChangeRecordMapper;
    @Mock
    private HotSkuStockGate hotSkuStockGate;
    @Mock
    private SmartlectMetrics metrics;
    @InjectMocks
    private SkuStockService service;

    @Test
    void duplicateRefundBusinessKeyDoesNotRestoreTwice() {
        RefundStockRestoreDTO dto = refund("refund-1");
        when(stockChangeRecordMapper.insertIgnore(
                "refund-1", "REFUND_RESTORE", "p1", "sku1", 2))
                .thenReturn(0);

        assertEquals(0, service.restoreRefundStock(dto));
        verify(skuStockMapper, never()).changeStock("p1", "sku1", 2);
    }

    @Test
    void firstRefundRestoreChangesStockInSameTransaction() {
        RefundStockRestoreDTO dto = refund("refund-2");
        when(stockChangeRecordMapper.insertIgnore(
                "refund-2", "REFUND_RESTORE", "p1", "sku1", 2))
                .thenReturn(1);
        when(skuStockMapper.changeStock("p1", "sku1", 2)).thenReturn(1);

        assertEquals(1, service.restoreRefundStock(dto));
    }

    @Test
    void orderRestoreMergesSkuQuantityAndUsesStableBusinessKey() {
        OrderStockRestoreDTO dto = orderRestore("pay-1", 2, 3);
        when(stockChangeRecordMapper.exists("order-deduct:pay-1")).thenReturn(1);
        when(stockChangeRecordMapper.insertIgnore(
                argThat(key -> key.startsWith("order-close:") && key.length() == 76),
                eq("ORDER_CLOSE_RESTORE"), eq("p1"), eq("sku1"), eq(5)))
                .thenReturn(1);
        when(skuStockMapper.changeStock("p1", "sku1", 5)).thenReturn(1);

        assertEquals(1, service.restoreOrderStock(dto));
        verify(skuStockMapper).changeStock("p1", "sku1", 5);
        verify(hotSkuStockGate).restoreOrder(eq("pay-1"),
                argThat(changes -> changes.get("p1\0sku1") == 5));
    }

    @Test
    void duplicateOrderRestoreDoesNotRestoreSkuTwice() {
        OrderStockRestoreDTO dto = orderRestore("pay-2", 4);
        when(stockChangeRecordMapper.exists("order-deduct:pay-2")).thenReturn(1);
        when(stockChangeRecordMapper.insertIgnore(
                argThat(key -> key.startsWith("order-close:")),
                eq("ORDER_CLOSE_RESTORE"), eq("p1"), eq("sku1"), eq(4)))
                .thenReturn(0);

        assertEquals(0, service.restoreOrderStock(dto));
        verify(skuStockMapper, never()).changeStock("p1", "sku1", 4);
    }

    @Test
    void differentPaymentAggregatesUseDifferentRestoreKeys() {
        OrderStockRestoreDTO first = orderRestore("pay-a", 1);
        OrderStockRestoreDTO second = orderRestore("pay-b", 1);
        when(stockChangeRecordMapper.exists("order-deduct:pay-a")).thenReturn(1);
        when(stockChangeRecordMapper.exists("order-deduct:pay-b")).thenReturn(1);
        when(stockChangeRecordMapper.insertIgnore(
                argThat(key -> key != null), eq("ORDER_CLOSE_RESTORE"),
                eq("p1"), eq("sku1"), eq(1)))
                .thenReturn(0);

        service.restoreOrderStock(first);
        service.restoreOrderStock(second);

        var keyCaptor = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(stockChangeRecordMapper, org.mockito.Mockito.times(2)).insertIgnore(
                keyCaptor.capture(), eq("ORDER_CLOSE_RESTORE"),
                eq("p1"), eq("sku1"), eq(1));
        assertEquals(2, keyCaptor.getAllValues().stream().distinct().count());
        assertTrue(keyCaptor.getAllValues().stream().allMatch(key -> key.length() == 76));
    }

    @Test
    void deductBusinessKeySkipsSecondApply() {
        com.smartlect.api.dto.SkuStockBatchChangeDTO batch = new com.smartlect.api.dto.SkuStockBatchChangeDTO();
        SkuStockChangeDTO item = new SkuStockChangeDTO();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku1");
        item.setChangeAmount(-2);
        batch.setItems(List.of(item));
        batch.setBusinessKey("order-deduct:pay-1");
        when(stockChangeRecordMapper.insertIgnore(
                "order-deduct:pay-1", "ORDER_DEDUCT", "p1", "sku1", 2))
                .thenReturn(0);

        assertEquals(0, service.changeStockBatch(batch));
        verify(skuStockMapper, never()).changeStock("p1", "sku1", -2);
    }

    @Test
    void firstDeductClaimsBusinessKeyThenChangesStock() {
        com.smartlect.api.dto.SkuStockBatchChangeDTO batch = new com.smartlect.api.dto.SkuStockBatchChangeDTO();
        SkuStockChangeDTO item = new SkuStockChangeDTO();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku1");
        item.setChangeAmount(-2);
        batch.setItems(List.of(item));
        batch.setBusinessKey("order-deduct:pay-2");
        when(stockChangeRecordMapper.insertIgnore(
                "order-deduct:pay-2", "ORDER_DEDUCT", "p1", "sku1", 2))
                .thenReturn(1);
        when(skuStockMapper.changeStock("p1", "sku1", -2)).thenReturn(1);

        assertEquals(1, service.changeStockBatch(batch));
        verify(skuStockMapper).changeStock("p1", "sku1", -2);
        verify(hotSkuStockGate).reserve(eq("order-deduct:pay-2"),
                argThat(changes -> changes.get("p1\0sku1") == -2));
        verify(hotSkuStockGate).commit(eq("order-deduct:pay-2"),
                argThat(changes -> changes.get("p1\0sku1") == -2));
    }

    @Test
    void deductDbFailureReleasesRedisReservation() {
        com.smartlect.api.dto.SkuStockBatchChangeDTO batch = new com.smartlect.api.dto.SkuStockBatchChangeDTO();
        SkuStockChangeDTO item = new SkuStockChangeDTO();
        item.setProductId("p1");
        item.setPropertyValueIdHash("sku1");
        item.setChangeAmount(-2);
        batch.setItems(List.of(item));
        batch.setBusinessKey("order-deduct:pay-db-fail");
        when(stockChangeRecordMapper.insertIgnore(
                "order-deduct:pay-db-fail", "ORDER_DEDUCT", "p1", "sku1", 2))
                .thenReturn(1);
        when(skuStockMapper.changeStock("p1", "sku1", -2)).thenReturn(0);

        org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.BusinessException.class,
                () -> service.changeStockBatch(batch));
        verify(hotSkuStockGate).release(eq("order-deduct:pay-db-fail"),
                argThat(changes -> changes.get("p1\0sku1") == -2));
    }

    @Test
    void orderRestoreSkipsWhenDeductRecordMissing() {
        // ADR-0003 防库存虚增：扣减失败留下的待付款单被关闭时，deduct 账本无记录，
        // 恢复必须整体跳过——既不加库存，也不写 order-close 恢复记录。
        OrderStockRestoreDTO dto = orderRestore("pay-orphan", 2);
        when(stockChangeRecordMapper.exists("order-deduct:pay-orphan")).thenReturn(0);

        assertEquals(0, service.restoreOrderStock(dto));
        verify(skuStockMapper, never()).changeStock("p1", "sku1", 2);
        verify(stockChangeRecordMapper, never()).insertIgnore(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void orderRestoreKeepsDeductRecordAsAuditTrail() {
        // ADR-0003：正常"扣过再关"的恢复照常执行；deduct 账本记录保留作审计链
        // （deleteByBusinessKey 已移除，账本只增不删）。
        OrderStockRestoreDTO dto = orderRestore("pay-release", 2);
        when(stockChangeRecordMapper.exists("order-deduct:pay-release")).thenReturn(1);
        when(stockChangeRecordMapper.insertIgnore(
                argThat(key -> key.startsWith("order-close:")),
                eq("ORDER_CLOSE_RESTORE"), eq("p1"), eq("sku1"), eq(2)))
                .thenReturn(1);
        when(skuStockMapper.changeStock("p1", "sku1", 2)).thenReturn(1);

        assertEquals(1, service.restoreOrderStock(dto));
        verify(skuStockMapper).changeStock("p1", "sku1", 2);
    }

    @Test
    void cancellationStatusRequiresEveryPersistedSkuQuantityWithoutMutatingStock() {
        OrderStockRestoreDTO dto = orderRestore("pay-check", 2, 3);
        when(stockChangeRecordMapper.existsOrderRestore(
                org.mockito.ArgumentMatchers.startsWith("order-close:"), eq(5))).thenReturn(0, 1);
        org.junit.jupiter.api.Assertions.assertFalse(service.isOrderStockApplied(dto));
        assertTrue(service.isOrderStockApplied(dto));
        org.mockito.Mockito.verifyNoInteractions(skuStockMapper);
        verify(stockChangeRecordMapper, never()).insertIgnore(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt());
    }

    private static RefundStockRestoreDTO refund(String key) {
        RefundStockRestoreDTO dto = new RefundStockRestoreDTO();
        dto.setRefundRequestId(key);
        dto.setBusinessKey(key);
        dto.setProductId("p1");
        dto.setPropertyValueIdHash("sku1");
        dto.setChangeAmount(2);
        return dto;
    }

    private static OrderStockRestoreDTO orderRestore(String payOrderId, int... quantities) {
        OrderStockRestoreDTO dto = new OrderStockRestoreDTO();
        dto.setPayOrderId(payOrderId);
        dto.setItems(java.util.Arrays.stream(quantities)
                .mapToObj(quantity -> {
                    SkuStockChangeDTO item = new SkuStockChangeDTO();
                    item.setProductId("p1");
                    item.setPropertyValueIdHash("sku1");
                    item.setChangeAmount(quantity);
                    return item;
                })
                .toList());
        return dto;
    }
}
