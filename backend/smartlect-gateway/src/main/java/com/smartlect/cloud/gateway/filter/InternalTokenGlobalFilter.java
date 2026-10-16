package com.smartlect.cloud.gateway.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.cloud.gateway.config.GatewayInternalProperties;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * /internal/** 的令牌校验**安全网**：网关当前没有任何 /internal 路由（内部流量走本机直连或
 * Dubbo，见 application.yml 的路由表注释），所以该过滤器在现役配置下**不会执行**。
 * 保留它是为了"万一有人加了一条 /internal 路由"时不至于静默放行——校验本身是 fail-closed
 * （令牌为空一律 401）。2026-10-16 审计曾把它标为死代码；结论是保留 + 把注释写实，
 * 而不是删掉一道潜在的安全闸。
 */
@Component
public class InternalTokenGlobalFilter implements GlobalFilter, Ordered {

    private static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";
    private static final int CODE_UNAUTHORIZED = 401;

    private final GatewayInternalProperties internalProperties;
    private final ObjectMapper objectMapper;

    public InternalTokenGlobalFilter(GatewayInternalProperties internalProperties,
                                     ObjectMapper objectMapper) {
        this.internalProperties = internalProperties;
        this.objectMapper = objectMapper;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String path = exchange.getRequest().getURI().getPath();
        if (path == null || !path.startsWith("/internal/")) {
            return chain.filter(exchange);
        }
        if (HttpMethod.OPTIONS.equals(exchange.getRequest().getMethod())) {
            return chain.filter(exchange);
        }
        if (!internalProperties.isAuthEnabled()) {
            return chain.filter(exchange);
        }
        String expected = internalProperties.getToken();
        String actual = exchange.getRequest().getHeaders().getFirst(INTERNAL_TOKEN_HEADER);
        if (tokenMatches(expected, actual)) {
            return chain.filter(exchange);
        }
        return unauthorized(exchange, "invalid internal token");
    }

    private static boolean tokenMatches(String expected, String actual) {
        if (!StringUtils.hasText(expected) || actual == null) {
            return false;
        }
        byte[] left = expected.getBytes(StandardCharsets.UTF_8);
        byte[] right = actual.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(left, right);
    }

    private Mono<Void> unauthorized(ServerWebExchange exchange, String msg) {
        exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "error");
        body.put("code", CODE_UNAUTHORIZED);
        body.put("info", msg);
        body.put("data", null);
        byte[] bytes;
        try {
            bytes = objectMapper.writeValueAsBytes(body);
        } catch (JsonProcessingException e) {
            bytes = ("{\"status\":\"error\",\"code\":401,\"info\":\"" + msg + "\",\"data\":null}")
                    .getBytes(StandardCharsets.UTF_8);
        }
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        return -200;
    }
}
