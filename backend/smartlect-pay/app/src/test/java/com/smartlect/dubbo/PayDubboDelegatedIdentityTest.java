package com.smartlect.dubbo;

import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.controller.internal.PayInternalController;
import com.smartlect.security.DelegatedUserIdentity;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.when;

/**
 * Dubbo provider 必须为 getPayUrl 注入委托身份：pay 域取支付表单前的归属校验
 * （PayInternalService.getPayUrl）依赖它，而 Dubbo 线程没有 HTTP 上下文——
 * 不注入会让"支付意图已存在"的 live 取表单路径必然 401（2026-10-17 审计 H-1）。
 */
@ExtendWith(MockitoExtension.class)
class PayDubboDelegatedIdentityTest {

    @Mock
    private PayInternalController controller;

    @InjectMocks
    private PayDubboServiceImpl service;

    @Test
    void getPayUrlPropagatesCallerIdentityAndCleansUp() {
        PayUrlRequestDTO dto = new PayUrlRequestDTO("mock", "pay-1", "subject", BigDecimal.ONE);
        when(controller.getPayUrl(dto)).thenAnswer(invocation -> {
            // provider 调用期间，委托身份必须可见（归属校验靠它）
            assertEquals("u-42", DelegatedUserIdentity.require());
            return null;
        });

        service.getPayUrl(dto, "u-42");

        // 调用结束必须清理 ThreadLocal，避免污染 Dubbo 线程池里的后续任务
        assertThrows(RuntimeException.class, DelegatedUserIdentity::require);
    }
}
