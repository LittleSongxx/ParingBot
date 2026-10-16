package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderInfoInitialPaymentTest {

    @Mock
    private PayRpcSupport payRpcSupport;

    private OrderCreationService service;

    @BeforeEach
    void setUp() {
        // requestInitialPayInfoBestEffort 已随批次二拆分移入 OrderCreationService；
        // 该方法只依赖 payRpcSupport，其余依赖传 null 即可。
        service = new OrderCreationService(null, null, null, null, null,
                null, null, null, null, null, payRpcSupport, null, null, null, null, null, null);
    }

    @Test
    void successfulPaymentFormIsReturnedUnchanged() {
        BigDecimal amount = new BigDecimal("19.90");
        PayInfoDTO expected = new PayInfoDTO("<form>pay</form>", "pay-1", amount);
        when(payRpcSupport.getPayUrl("mock", "pay-1", "subject", amount, "u1"))
                .thenReturn(expected);

        PayInfoDTO actual = service.requestInitialPayInfoBestEffort(
                "mock", "pay-1", "subject", amount, "u1");

        assertSame(expected, actual);
    }

    @Test
    void unavailablePaymentFormKeepsPayableOrderIdentity() {
        BigDecimal amount = new BigDecimal("19.90");
        when(payRpcSupport.getPayUrl("mock", "pay-2", "subject", amount, "u1"))
                .thenThrow(new BusinessException("provider unavailable"));

        PayInfoDTO actual = service.requestInitialPayInfoBestEffort(
                "mock", "pay-2", "subject", amount, "u1");

        assertNull(actual.getPayInfo());
        assertEquals("pay-2", actual.getPayOrderId());
        assertEquals(amount, actual.getAmount());
    }

    @Test
    void zeroAmountSkipsChannelAndStaysFree() {
        PayInfoDTO actual = service.requestInitialPayInfoBestEffort(
                "mock", "pay-free", "subject", BigDecimal.ZERO, "u1");

        assertEquals("FREE", actual.getPayInfo());
        assertEquals("pay-free", actual.getPayOrderId());
        assertEquals(new BigDecimal("0.00"), actual.getAmount());
    }
}
