package com.smartlect.cloud.gateway.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsWebFilter;
import org.springframework.web.util.pattern.PathPatternParser;

import java.util.Arrays;

/**
 * CORS（ADR-0023）：此前全仓无任何 CORS 配置（隐性依赖 nginx 同源拓扑，跨域直接坏）。
 * 默认关闭；配置 smartlect.cors.allowed-origin-patterns 后启用（逗号分隔，
 * 开发环境如 http://localhost:18180,http://127.0.0.1:18180），携带凭证。
 */
@Configuration
public class CorsConfig {

    @Value("${smartlect.cors.allowed-origin-patterns:}")
    private String allowedOriginPatterns;

    @Bean
    public CorsWebFilter corsWebFilter() {
        if (allowedOriginPatterns == null || allowedOriginPatterns.isBlank()) {
            return new CorsWebFilter(new org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource());
        }
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(Arrays.asList(allowedOriginPatterns.split(",")));
        config.addAllowedMethod("*");
        config.addAllowedHeader("*");
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);
        org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource source =
                new org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource(new PathPatternParser());
        source.registerCorsConfiguration("/**", config);
        return new CorsWebFilter(source);
    }
}
