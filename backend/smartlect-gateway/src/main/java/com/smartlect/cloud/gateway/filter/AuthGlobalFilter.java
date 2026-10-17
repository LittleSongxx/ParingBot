package com.smartlect.cloud.gateway.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.cloud.gateway.config.GatewayAuthProperties;
import com.smartlect.cloud.gateway.support.GatewayTokenResolver;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class AuthGlobalFilter implements GlobalFilter, Ordered {

    // Sa-Token 用户端会话键（ADR-0008 Step 1）：值是 loginId 裸字符串，无需解析 JSON
    private static final String REDIS_KEY_TOKEN_WEB = "token:login:token:";
    // 管理端 loginType=admin（StpAdminLogic），Sa-Token 1.39 实键为 adminToken:admin:token:*
    private static final String REDIS_KEY_TOKEN_ADMIN = "adminToken:admin:token:";
    private static final String USER_ID_HEADER = "X-User-Id";
    private static final String USER_VERIFIED_HEADER = "X-User-Token-Verified";
    private static final String ADMIN_VERIFIED_HEADER = "X-Admin-Token-Verified";
    // Gateway intentionally does not depend on the Servlet-based smartlect-common module.
    private static final List<String> INTERNAL_IDENTITY_HEADERS = List.of(
            "X-Internal-Token", "X-Internal-Ops-Token", "X-Smartlect-User-Id",
            "X-Admin-Id", "X-Admin-Account", "X-Admin-Roles", "X-Admin-Permissions",
            "X-Admin-Timestamp", "X-Admin-Nonce", "X-Admin-Body-SHA256",
            "X-Admin-Signature", "X-Admin-Key-Id",
            // 与 InternalApiHeaders 全量对齐：网关随后自行写入该头（TraceIdGlobalFilter），
            // 客户端传入值先剥掉，防日志/链路伪造（2026-10-16 审计 L-3）
            "X-Trace-Id");
    private static final int CODE_LOGIN_TIMEOUT = 901;

    private final GatewayAuthProperties authProperties;
    private final ReactiveStringRedisTemplate reactiveStringRedisTemplate;
    private final ObjectMapper objectMapper;
    private final AntPathMatcher pathMatcher = new AntPathMatcher();

    public AuthGlobalFilter(GatewayAuthProperties authProperties,
                            ReactiveStringRedisTemplate reactiveStringRedisTemplate,
                            ObjectMapper objectMapper) {
        this.authProperties = authProperties;
        this.reactiveStringRedisTemplate = reactiveStringRedisTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerWebExchange sanitizedExchange = removeClientSuppliedIdentityHeaders(exchange);
        if (!authProperties.isEnabled()) {
            return chain.filter(sanitizedExchange);
        }
        ServerHttpRequest request = sanitizedExchange.getRequest();
        if (HttpMethod.OPTIONS.equals(request.getMethod())) {
            return chain.filter(sanitizedExchange);
        }
        String path = request.getURI().getPath();
        // The AI API authenticates cookies through Java introspection on every request.
        // This permits shopping visitors; merchant routes still require a valid admin cookie there.
        if (path.startsWith("/api/assistant/") || path.startsWith("/admin-api/assistant/")) {
            return chain.filter(sanitizedExchange);
        }
        if (isInfraPath(path) || isInternalPath(path)) {
            return chain.filter(sanitizedExchange);
        }

        if (path.startsWith("/admin-api/")) {
            if (matchAny(path, authProperties.getAdminExcludePaths())) {
                return chain.filter(sanitizedExchange);
            }
            String adminToken = GatewayTokenResolver.resolveAdminToken(exchange);
            if (!StringUtils.hasText(adminToken)) {
                return unauthorized(sanitizedExchange, "登录超时");
            }
            // 校验通过即放行：下游服务各自经 Sa-Token 会话内省取得身份；
            // 身份信任头不在此下发（历史上设置的 X-User-Id/X-*-Token-Verified 无任何消费者，已删）。
            return reactiveStringRedisTemplate.hasKey(REDIS_KEY_TOKEN_ADMIN + adminToken)
                    .flatMap(exists -> Boolean.TRUE.equals(exists)
                            ? chain.filter(sanitizedExchange)
                            : unauthorized(sanitizedExchange, "登录超时"));
        }

        if (path.startsWith("/api/")) {
            if (path.startsWith("/api/") && matchAny(path, authProperties.getWebExcludePaths())) {
                return chain.filter(sanitizedExchange);
            }
            String token = GatewayTokenResolver.resolveWebToken(exchange);
            if (!StringUtils.hasText(token)) {
                return unauthorized(sanitizedExchange, "登录超时");
            }
            return reactiveStringRedisTemplate.opsForValue().get(REDIS_KEY_TOKEN_WEB + token)
                    .defaultIfEmpty("")
                    .flatMap(loginId -> StringUtils.hasText(loginId)
                            ? chain.filter(sanitizedExchange)
                            : unauthorized(sanitizedExchange, "登录超时"));
        }

        return chain.filter(sanitizedExchange);
    }

    private ServerWebExchange removeClientSuppliedIdentityHeaders(ServerWebExchange exchange) {
        ServerHttpRequest sanitized = exchange.getRequest().mutate()
                .headers(headers -> {
                    headers.remove(USER_ID_HEADER);
                    headers.remove(USER_VERIFIED_HEADER);
                    headers.remove(ADMIN_VERIFIED_HEADER);
                    INTERNAL_IDENTITY_HEADERS.forEach(headers::remove);
                })
                .build();
        return exchange.mutate().request(sanitized).build();
    }

    private boolean isInfraPath(String path) {
        // 仅放行健康检查，避免整站 actuator 暴露业务细节
        return "/actuator/health".equals(path)
                || "/actuator/health/liveness".equals(path)
                || "/actuator/health/readiness".equals(path)
                || "/favicon.ico".equals(path);
    }

    /** Session auth is skipped; {@link InternalTokenGlobalFilter} validates the token. */
    private boolean isInternalPath(String path) {
        return path != null && path.startsWith("/internal/");
    }

    private boolean matchAny(String path, List<String> patterns) {
        if (patterns == null || patterns.isEmpty()) {
            return false;
        }
        for (String pattern : patterns) {
            if (!StringUtils.hasText(pattern)) {
                continue;
            }
            if (pathMatcher.match(pattern.trim(), path)) {
                return true;
            }
        }
        return false;
    }

    private Mono<Void> unauthorized(ServerWebExchange exchange, String msg) {
        exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "error");
        body.put("code", CODE_LOGIN_TIMEOUT);
        body.put("info", msg);
        body.put("data", null);
        byte[] bytes;
        try {
            bytes = objectMapper.writeValueAsBytes(body);
        } catch (JsonProcessingException e) {
            bytes = ("{\"code\":901,\"info\":\"" + msg + "\"}").getBytes(StandardCharsets.UTF_8);
        }
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        return -100;
    }
}
