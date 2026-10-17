package com.smartlect.cloud.gateway.config;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
public class GatewayProductionSafetyValidator {

    private static final Logger log = LoggerFactory.getLogger(GatewayProductionSafetyValidator.class);
    private static final String WEAK_INTERNAL = "your-token";

    @Value("${smartlect.production-ready:false}")
    private boolean productionReady;

    @Value("${smartlect.internal.token:}")
    private String internalToken;

    /** 空值在 Spring Boot 里等价于监听全部网卡；与 0.0.0.0 / :: 同属通配绑定。 */
    @Value("${server.address:}")
    private String serverAddress;

    @Value("${management.endpoints.web.exposure.include:health,info}")
    private String actuatorExposure;

    @Value("${smartlect.allow-wildcard-bind:false}")
    private boolean allowWildcardBind;

    @PostConstruct
    public void validate() {
        if (!productionReady) {
            log.warn("smartlect.production-ready=false（Gateway）：上线前请设为 true 并配置强内部 Token");
            return;
        }
        if (!StringUtils.hasText(internalToken) || WEAK_INTERNAL.equals(internalToken)) {
            throw new IllegalStateException("生产就绪校验失败: 请设置强 SMARTLECT_INTERNAL_TOKEN");
        }
        if (wildcardBind() && exposesPrometheus() && !allowWildcardBind) {
            // 网关端口是唯一对公入口：绑通配地址时，若安全组没有封住 18080，
            // 外部可绕过 nginx 直连网关并读取 actuator 指标。
            throw new IllegalStateException("生产就绪校验失败: Gateway 监听通配地址("
                    + (StringUtils.hasText(serverAddress) ? serverAddress : "未设置（等价 0.0.0.0）")
                    + ")且 actuator 暴露 prometheus——请绑定内网 IP，或设置 "
                    + "SMARTLECT_ALLOW_WILDCARD_BIND=true 并确认安全组封住 18080");
        }
        log.info("Gateway 生产就绪校验通过");
    }

    private boolean wildcardBind() {
        return !StringUtils.hasText(serverAddress)
                || "0.0.0.0".equals(serverAddress)
                || "::".equals(serverAddress)
                || "[::]".equals(serverAddress);
    }

    private boolean exposesPrometheus() {
        if (!StringUtils.hasText(actuatorExposure)) {
            return false;
        }
        for (String item : actuatorExposure.split(",")) {
            String value = item.trim();
            if ("*".equals(value) || "prometheus".equals(value)) {
                return true;
            }
        }
        return false;
    }
}
