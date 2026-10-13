package com.smartlect.api.dubbo;

import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

import jakarta.annotation.PostConstruct;

/**
 * Dubbo 公共配置：把 Spring 环境里的内部令牌桥接给 SPI Filter（非 Spring 托管）。
 */
@Configuration
public class DubboCommonConfiguration {

    @Value("${smartlect.internal.token:}")
    private String internalToken;

    @Resource
    private org.springframework.core.env.Environment environment;

    @PostConstruct
    public void bridgeInternalToken() {
        String token = internalToken;
        if (token == null || token.isBlank()) {
            token = environment.getProperty("SMARTLECT_INTERNAL_TOKEN");
        }
        DubboInternalAuthFilter.TokenHolder.set(token == null ? "" : token);
    }
}
