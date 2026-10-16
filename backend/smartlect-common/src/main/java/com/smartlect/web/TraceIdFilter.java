package com.smartlect.web;

import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.utils.StringTools;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class TraceIdFilter extends OncePerRequestFilter {

    /** 32 位十六进制（W3C trace-id 形态）或 UUID 去横线形态。 */
    static boolean isValidTraceId(String value) {
        return value != null && value.matches("^[0-9a-fA-F]{32}$");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String w3cTraceId = W3cTraceContext.traceIdFromTraceparent(request.getHeader(W3cTraceContext.TRACEPARENT));
        String correlationId;
        if (w3cTraceId != null) {
            correlationId = w3cTraceId;
        } else if (isValidTraceId(request.getHeader(InternalApiHeaders.TRACE_ID))) {
            // 只接受合法格式：直连服务端口时该头由客户端提供，未校验会把任意内容写进日志
            // 上下文与响应头（日志伪造/注入，2026-10-16 审计）
            correlationId = request.getHeader(InternalApiHeaders.TRACE_ID);
        } else {
            // 日志关联，不是 OTEL trace_id，也不伪造 traceparent。
            correlationId = UUID.randomUUID().toString().replace("-", "");
        }
        MDC.put(InternalApiHeaders.TRACE_ID_MDC, correlationId);
        response.setHeader(InternalApiHeaders.TRACE_ID, correlationId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.remove(InternalApiHeaders.TRACE_ID_MDC);
        }
    }
}
