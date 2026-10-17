package com.smartlect.biz;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.biz.impl.PayChannel4Mock;
import com.smartlect.controller.AGlobalExceptionHandlerController;
import com.smartlect.controller.internal.MockPaymentController;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.security.MockPaymentSignatureVerifier;
import com.smartlect.web.InternalApiAuthFilter;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PayAttemptServiceTest {
    @Test
    void onlyExactStringIdentifiersCanReachTheProvider() throws Exception {
        var json = new ObjectMapper();
        assertEquals(new PayAttemptService.Request("attempt-1", "pay-1"),
                PayAttemptService.parse(json.readTree("{\"attemptId\":\"attempt-1\",\"payOrderId\":\"pay-1\"}")));
        for (String value : List.of("{}", "[]", "null", "{\"attemptId\":true,\"payOrderId\":\"pay-1\"}",
                "{\"attemptId\":\"\",\"payOrderId\":\"pay-1\"}",
                "{\"attemptId\":\"attempt-1\",\"payOrderId\":\"pay-1\",\"attemptStatus\":\"FAILED\"}",
                "{\"attemptId\":\"attempt-1\",\"payOrderId\":\"pay-1\",\"occurredAt\":\"2026-01-01\"}",
                "{\"attemptId\":\"attempt-1\",\"payOrderId\":\"pay-1\",\"userId\":\"other\"}")) {
            assertThrows(HttpBusinessException.class, () -> PayAttemptService.parse(json.readTree(value)));
        }
    }

    @Test
    void internalTokenAndDelegatedOwnerAreBothRequired() throws Exception {
        PayAttemptService attempts = mock(PayAttemptService.class);
        var controller = new MockPaymentController(mock(PayChannel4Mock.class), mock(MockPaymentSignatureVerifier.class));
        ReflectionTestUtils.setField(controller, "attempts", attempts);
        InternalApiAuthFilter filter = new InternalApiAuthFilter();
        ReflectionTestUtils.setField(filter, "expectedToken", "synthetic-internal");
        ReflectionTestUtils.setField(filter, "authEnabled", true);
        var mvc = MockMvcBuilders.standaloneSetup(controller).addFilters(filter)
                .setControllerAdvice(new AGlobalExceptionHandlerController()).build();
        String body = "{\"attemptId\":\"attempt-1\",\"payOrderId\":\"pay-1\"}";
        for (String path : List.of("/internal/pay/mock/decline", "/internal/pay/mock/attempt")) {
            mvc.perform(post(path).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isUnauthorized());
            mvc.perform(post(path).header("X-Internal-Token", "synthetic-internal")
                    .contentType(MediaType.APPLICATION_JSON).content(body)).andExpect(status().isUnauthorized());
        }
        verifyNoInteractions(attempts);
        mvc.perform(post("/internal/pay/mock/decline").header("X-Internal-Token", "synthetic-internal")
                .header("X-Smartlect-User-Id", "owner-1").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk());
        verify(attempts).decline("owner-1", new PayAttemptService.Request("attempt-1", "pay-1"));
        mvc.perform(post("/internal/pay/mock/decline").header("X-Internal-Token", "synthetic-internal")
                .header("X-Smartlect-User-Id", "owner-1").contentType(MediaType.APPLICATION_JSON)
                .content(body.substring(0, body.length() - 1) + ",\"amount\":1}"))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void nonpending_wrongOwner_and_realChannel_do_not_create_attempts_or_events() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
                var service = new PayAttemptService(jdbc);
        var request = new PayAttemptService.Request("attempt-1", "pay-1");
        when(jdbc.queryForList(startsWith("SELECT user_id"), anyString())).thenReturn(List.of());
        for (int state : List.of(1, 2, 3)) {
            when(jdbc.queryForList(startsWith("SELECT pay_order_id"), anyString()))
                    .thenReturn(List.of(intent("owner-1", "mock", state)));
            assertThrows(HttpBusinessException.class, () -> service.decline("owner-1", request));
        }
        when(jdbc.queryForList(startsWith("SELECT pay_order_id"), anyString()))
                .thenReturn(List.of(intent("owner-1", "retired_channel", 0)), List.of(intent("other", "mock", 0)));
        assertEquals(403, assertThrows(HttpBusinessException.class,
                () -> service.decline("owner-1", request)).getHttpStatus());
        assertEquals(403, assertThrows(HttpBusinessException.class,
                () -> service.decline("owner-1", request)).getHttpStatus());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    private static Map<String, Object> intent(String owner, String channel, int state) {
        return Map.of("pay_order_id", "pay-1", "order_id", "order-1", "user_id", owner,
                "pay_channel", channel, "pay_amount", new BigDecimal("90.00"), "trade_status", state);
    }
}
