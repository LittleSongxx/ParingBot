package com.smartlect.cloud.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

class TraceIdGlobalFilterTest {

    private final TraceIdGlobalFilter filter = new TraceIdGlobalFilter();
    private final GatewayFilterChain chain = mock(GatewayFilterChain.class);

    @Test
    void w3cTraceparentTraceIdIsExtractedAndPropagatedDownstream() {
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/x")
                .header("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"));
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        when(chain.filter(any())).thenAnswer(invocation -> {
            downstream.set(invocation.getArgument(0, ServerWebExchange.class));
            return Mono.empty();
        });

        filter.filter(exchange, chain).block();

        // 下游（过滤链内的 mutated exchange）看到裁决后的追踪头
        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736",
                downstream.get().getRequest().getHeaders().getFirst(TraceIdGlobalFilter.X_TRACE_ID));
        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736",
                exchange.getResponse().getHeaders().getFirst(TraceIdGlobalFilter.X_TRACE_ID));
    }

    @Test
    void forgedTraceIdHeaderIsOverriddenByGatewayDecision() {
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/x")
                .header(TraceIdGlobalFilter.X_TRACE_ID, "4bf92f3577b34da6a3ce929d0e0e4736"));
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        when(chain.filter(any())).thenAnswer(invocation -> {
            downstream.set(invocation.getArgument(0, ServerWebExchange.class));
            return Mono.empty();
        });

        filter.filter(exchange, chain).block();

        // 无 traceparent 时，合法的 32 位十六进制 X-Trace-Id 被采纳
        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736",
                downstream.get().getRequest().getHeaders().getFirst(TraceIdGlobalFilter.X_TRACE_ID));
    }

    @Test
    void missingTraceContextGeneratesFreshTraceIdAndEchoesIt() {
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/x"));
        AtomicReference<ServerWebExchange> downstream = new AtomicReference<>();
        when(chain.filter(any())).thenAnswer(invocation -> {
            downstream.set(invocation.getArgument(0, ServerWebExchange.class));
            return Mono.empty();
        });

        filter.filter(exchange, chain).block();

        String generated = downstream.get().getRequest().getHeaders().getFirst(TraceIdGlobalFilter.X_TRACE_ID);
        assertNotNull(generated);
        assertTrue(generated.matches("[0-9a-f]{32}"), "生成的 traceId 应为 32 位十六进制");
        assertEquals(generated, exchange.getResponse().getHeaders().getFirst(TraceIdGlobalFilter.X_TRACE_ID));
    }

    @Test
    void malformedTraceparentFallsBackToGeneration() {
        assertEquals(null, TraceIdGlobalFilter.traceIdFromTraceparent("not-a-traceparent"));
        assertEquals(null, TraceIdGlobalFilter.traceIdFromTraceparent("00-short-span-01"));
    }
}
