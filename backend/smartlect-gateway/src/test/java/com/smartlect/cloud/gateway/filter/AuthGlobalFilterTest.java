package com.smartlect.cloud.gateway.filter;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.cloud.gateway.config.GatewayAuthProperties;
import com.smartlect.cloud.gateway.config.GatewayInternalProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.ReactiveValueOperations;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.List;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verifyNoInteractions;

@ExtendWith(MockitoExtension.class)
class AuthGlobalFilterTest {

    @Mock
    private ReactiveStringRedisTemplate redisTemplate;
    @Mock
    private ReactiveValueOperations<String, String> valueOperations;

    private GatewayAuthProperties properties;
    private AuthGlobalFilter filter;

    @BeforeEach
    void setUp() {
        properties = new GatewayAuthProperties();
        properties.setEnabled(true);
        filter = new AuthGlobalFilter(properties, redisTemplate, new ObjectMapper());
    }

    @Test
    void authenticatedRequestStripsSpoofedIdentityHeadersInsteadOfOverwriting() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        // Sa-Token 键：token:login:token:{token} -> loginId 裸字符串
        when(valueOperations.get("token:login:token:valid-token"))
                .thenReturn(Mono.just("trusted-user"));
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/orders")
                        .header("token", "valid-token")
                        .header("X-User-Id", "attacker")
                        .header("X-User-Token-Verified", "forged")
                        .header("X-Admin-Token-Verified", "forged")
                        .build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        filter.filter(exchange, capture(forwarded)).block();

        // 身份信任头一律剥离、不再下发：下游经 Sa-Token 会话内省自行取身份
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"));
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Token-Verified"));
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-Admin-Token-Verified"));
        assertEquals(HttpStatus.OK, exchange.getResponse().getStatusCode());
        assertEquals("downstream", exchange.getResponse().getBodyAsString().block());
    }

    @Test
    void missingOrInvalidSessionNeverCallsDownstream() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        // 键缺失或值为空白 loginId 均视为未登录
        for (Mono<String> loginId : List.of(Mono.<String>empty(), Mono.just(""), Mono.just("  "))) {
            when(valueOperations.get("token:login:token:expired")).thenReturn(loginId);
            MockServerWebExchange exchange = MockServerWebExchange.from(
                    MockServerHttpRequest.get("/api/orders").header("token", "expired").build());
            AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
            filter.filter(exchange, capture(forwarded)).block();
            assertNull(forwarded.get());
            assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
        }
    }

    @Test
    void exactWebSocketPathIsNotSessionAuthenticated() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/ws")
                        .header("token", "valid-token")
                        .build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        filter.filter(exchange, capture(forwarded)).block();

        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"));
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Token-Verified"));
        verifyNoInteractions(redisTemplate);
    }

    @Test
    void publicEndpointStillDropsClientSuppliedIdentityHeaders() {
        properties.setWebExcludePaths(List.of("/api/public/**"));
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/public/catalog")
                        .header("X-User-Id", "attacker")
                        .header("X-User-Token-Verified", "forged")
                        .build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        filter.filter(exchange, capture(forwarded)).block();

        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"));
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Token-Verified"));
    }

    @Test
    void assistantRoutesReachCookieBridgeAfterHeaderCleaningWithoutGatewaySessionAuth() {
        for (String path : List.of("/api/assistant/conversations", "/admin-api/assistant/session")) {
            MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.post(path)
                    .header("token", "forged-header-token").header("adminToken", "forged-admin-token")
                    .header("X-Internal-Token", "forged-service-token")
                    .header("X-Smartlect-User-Id", "forged-user").header("X-User-Id", "forged-user")
                    .header("X-Admin-Permissions", "admin:manage").header("X-Admin-Signature", "forged")
                    .build());
            AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
            filter.filter(exchange, capture(forwarded)).block();
            assertEquals(path, forwarded.get().getRequest().getURI().getPath());
            for (String header : List.of("X-Internal-Token", "X-Smartlect-User-Id", "X-User-Id",
                    "X-User-Token-Verified", "X-Admin-Permissions", "X-Admin-Signature", "X-Admin-Token-Verified")) {
                assertNull(forwarded.get().getRequest().getHeaders().getFirst(header));
            }
        }
        verifyNoInteractions(redisTemplate);
    }

    @Test
    void adminRoutesCheckAdminLoginTypeKeyPrefix() {
        when(redisTemplate.hasKey("adminToken:admin:token:valid-admin")).thenReturn(Mono.just(true));
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.post("/admin-api/order/loadDataList")
                        .header("adminToken", "valid-admin").build());
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        filter.filter(exchange, capture(forwarded)).block();

        // 校验通过放行，但不携带任何身份信任头（下游自行内省）
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-Admin-Token-Verified"));
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"));

        // 键不存在（旧前缀/过期/伪造）一律 401，不透传任何已验证标记
        when(redisTemplate.hasKey("adminToken:admin:token:stale-admin")).thenReturn(Mono.just(false));
        MockServerWebExchange stale = MockServerWebExchange.from(
                MockServerHttpRequest.post("/admin-api/order/loadDataList")
                        .header("adminToken", "stale-admin").build());
        AtomicReference<ServerWebExchange> staleForwarded = new AtomicReference<>();
        filter.filter(stale, capture(staleForwarded)).block();
        assertNull(staleForwarded.get());
        assertEquals(HttpStatus.UNAUTHORIZED, stale.getResponse().getStatusCode());
    }

    @Test
    void productReadPathsArePublicButOtherProductPathsRequireLogin() {
        properties.setWebExcludePaths(List.of("/api/product/loadCategory", "/api/product/loadCommendProduct",
                "/api/product/loadProduct", "/api/product/getProduct"));
        for (String path : List.of("/api/product/loadCategory", "/api/product/loadCommendProduct",
                "/api/product/loadProduct", "/api/product/getProduct")) {
            MockServerWebExchange exchange = MockServerWebExchange.from(
                    MockServerHttpRequest.post(path).header("X-User-Id", "attacker").build());
            AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
            filter.filter(exchange, capture(forwarded)).block();
            assertNotNull(forwarded.get());
            assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"));
        }
        // 精确白名单之外的商品路径仍必须登录；不能再用 /api/product/** 整前缀放行。
        MockServerWebExchange write = MockServerWebExchange.from(
                MockServerHttpRequest.post("/api/product/updatePrice").build());
        AtomicReference<ServerWebExchange> forwardedWrite = new AtomicReference<>();
        filter.filter(write, capture(forwardedWrite)).block();
        assertNull(forwardedWrite.get());
        assertEquals(HttpStatus.UNAUTHORIZED, write.getResponse().getStatusCode());
    }

    @Test
    void traditionalOrdersAndSimilarButDifferentPrefixesStillRequireLogin() {
        for (String path : List.of("/api/order/loadMyOrder", "/admin-api/order/loadDataList",
                "/api/assistant-other/session", "/admin-api/assistant-other/session")) {
            MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.post(path).build());
            AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
            filter.filter(exchange, capture(forwarded)).block();
            assertNull(forwarded.get());
            assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
        }
        verifyNoInteractions(redisTemplate);
    }

    @Test
    void publicRoutesDropAllReservedServiceHeadersEvenWhenSessionAuthIsDisabled() {
        List<String> reserved = List.of("X-Internal-Token", "X-Internal-Ops-Token", "X-Smartlect-User-Id",
                "X-Admin-Id", "X-Admin-Account", "X-Admin-Roles", "X-Admin-Permissions",
                "X-Admin-Timestamp", "X-Admin-Nonce", "X-Admin-Body-SHA256", "X-Admin-Signature",
                "X-Admin-Key-Id", "X-User-Id", "X-User-Token-Verified", "X-Admin-Token-Verified");
        properties.setWebExcludePaths(List.of("/api/public/**"));
        properties.setAdminExcludePaths(List.of("/admin-api/account/login"));
        for (boolean enabled : List.of(true, false)) {
            properties.setEnabled(enabled);
            for (String path : List.of("/api/public/catalog", "/admin-api/account/login", "/actuator/health")) {
                var request = MockServerHttpRequest.get(path).header("X-Admin-Confirm-Pwd", "user-confirmation");
                reserved.forEach(header -> request.header(header.toLowerCase(java.util.Locale.ROOT), "forged"));
                MockServerWebExchange exchange = MockServerWebExchange.from(request.build());
                AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
                filter.filter(exchange, capture(forwarded)).block();
                reserved.forEach(header -> assertNull(forwarded.get().getRequest().getHeaders().getFirst(header)));
                assertEquals("user-confirmation", forwarded.get().getRequest().getHeaders().getFirst("X-Admin-Confirm-Pwd"));
            }
        }
    }

    @Test
    void internalAuthenticationRunsBeforePreservingLegitimateDelegationHeaders() {
        GatewayInternalProperties internalProperties = new GatewayInternalProperties();
        internalProperties.setToken("service-secret");
        InternalTokenGlobalFilter internal = new InternalTokenGlobalFilter(internalProperties, new ObjectMapper());
        for (String token : List.of("wrong", "service-secret")) {
            MockServerWebExchange exchange = MockServerWebExchange.from(
                    MockServerHttpRequest.post("/internal/identity/introspect")
                            .header("X-Internal-Token", token)
                            .header("X-Smartlect-User-Id", "trusted-user")
                            .header("X-Admin-Signature", "service-signature").build());
            AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
            internal.filter(exchange, next -> filter.filter(next, capture(forwarded))).block();
            if (token.equals("wrong")) {
                assertNull(forwarded.get());
                assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
            } else {
                assertNotNull(forwarded.get());
                assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-Internal-Token"));
                assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-Smartlect-User-Id"));
                assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-Admin-Signature"));
            }
        }
    }

    private static GatewayFilterChain capture(AtomicReference<ServerWebExchange> forwarded) {
        return exchange -> {
            forwarded.set(exchange);
            exchange.getResponse().setStatusCode(HttpStatus.OK);
            return exchange.getResponse().writeWith(Mono.just(exchange.getResponse().bufferFactory()
                    .wrap("downstream".getBytes(StandardCharsets.UTF_8))));
        };
    }
}
