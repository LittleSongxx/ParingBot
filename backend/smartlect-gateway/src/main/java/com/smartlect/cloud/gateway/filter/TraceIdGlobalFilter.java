package com.smartlect.cloud.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.security.SecureRandom;

/**
 * 链路追踪入口过滤器（ADR-0021）：网关是外部流量的第一跳，负责统一生成/透传 traceId——
 * 服务间继续由 X-Trace-Id / traceparent 头 + MDC 贯穿（common 的 TraceIdFilter 与
 * Dubbo Filter 已就绪，此前缺的正是入口这一环，跨服务日志无法串联）。
 * order=-300：先于 internal(-200) 与 auth(-100)，所有下游过滤都能读到追踪头。
 * 网关不依赖 smartlect-common（架构约定），W3C 解析此处内联最小实现。
 */
@Component
public class TraceIdGlobalFilter implements GlobalFilter, Ordered {

    public static final String TRACEPARENT = "traceparent";
    public static final String X_TRACE_ID = "X-Trace-Id";
    static final int FILTER_ORDER = -300;

    private static final SecureRandom RANDOM = new SecureRandom();

    @Override
    public int getOrder() {
        return FILTER_ORDER;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String traceId = resolveTraceId(exchange.getRequest());
        ServerHttpRequest mutated = exchange.getRequest().mutate()
                .headers(headers -> {
                    // 剥掉客户端伪造的同名头，以本过滤器裁决值为准；traceparent 原样透传不伪造
                    headers.remove(X_TRACE_ID);
                    headers.set(X_TRACE_ID, traceId);
                })
                .build();
        exchange.getResponse().getHeaders().set(X_TRACE_ID, traceId);
        return chain.filter(exchange.mutate().request(mutated).build());
    }

    private static String resolveTraceId(ServerHttpRequest request) {
        String traceparent = request.getHeaders().getFirst(TRACEPARENT);
        String fromTraceparent = traceIdFromTraceparent(traceparent);
        if (fromTraceparent != null) {
            return fromTraceparent;
        }
        String provided = request.getHeaders().getFirst(X_TRACE_ID);
        if (provided != null && provided.matches("[0-9a-f]{16,32}")) {
            return provided;
        }
        return newTraceId();
    }

    /** W3C traceparent: {version}-{trace-id}-{span-id}-{flags}，取 trace-id 段。 */
    static String traceIdFromTraceparent(String traceparent) {
        if (traceparent == null) {
            return null;
        }
        String[] parts = traceparent.split("-");
        if (parts.length != 4) {
            return null;
        }
        String traceId = parts[1];
        return traceId.matches("[0-9a-f]{32}") ? traceId : null;
    }

    static String newTraceId() {
        byte[] bytes = new byte[16];
        RANDOM.nextBytes(bytes);
        StringBuilder builder = new StringBuilder(32);
        for (byte b : bytes) {
            builder.append(Character.forDigit((b >> 4) & 0xF, 16));
            builder.append(Character.forDigit(b & 0xF, 16));
        }
        return builder.toString();
    }
}
