package com.smartlect.cloud.gateway.config;

import com.alibaba.csp.sentinel.adapter.gateway.common.SentinelGatewayConstants;
import com.alibaba.csp.sentinel.adapter.gateway.common.api.ApiDefinition;
import com.alibaba.csp.sentinel.adapter.gateway.common.api.ApiPathPredicateItem;
import com.alibaba.csp.sentinel.adapter.gateway.common.api.ApiPredicateItem;
import com.alibaba.csp.sentinel.adapter.gateway.common.api.GatewayApiDefinitionManager;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayFlowRule;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayParamFlowItem;
import com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayRuleManager;
import com.alibaba.csp.sentinel.adapter.gateway.sc.callback.BlockRequestHandler;
import com.alibaba.csp.sentinel.adapter.gateway.sc.callback.GatewayCallbackManager;
import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRule;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager;
import jakarta.annotation.PostConstruct;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.server.ServerResponse;
import org.springframework.web.server.ServerWebExchange;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Configuration
public class SentinelGatewayConfig {

    // 网关模块未引入 lombok，手写 Logger
    private static final org.slf4j.Logger log =
            org.slf4j.LoggerFactory.getLogger(SentinelGatewayConfig.class);

    // ADR-0023：可选 Nacos 动态数据源——配置 smartlect.sentinel.gateway-rules-data-id 后，
    // 网关流控规则由配置中心热更（JSON 数组，字段同 GatewayFlowRule），代码注册的规则仅作兜底。
    @org.springframework.beans.factory.annotation.Value("${smartlect.sentinel.gateway-rules-data-id:}")
    private String gatewayRulesDataId;
    @org.springframework.beans.factory.annotation.Value("${spring.cloud.nacos.config.server-addr:}")
    private String nacosServerAddr;
    @org.springframework.beans.factory.annotation.Value("${spring.cloud.nacos.config.group:DEFAULT_GROUP}")
    private String nacosGroup;
    @org.springframework.beans.factory.annotation.Value("${spring.cloud.nacos.config.username:}")
    private String nacosUsername;
    @org.springframework.beans.factory.annotation.Value("${spring.cloud.nacos.config.password:}")
    private String nacosPassword;
    @org.springframework.beans.factory.annotation.Value("${spring.cloud.nacos.config.namespace:}")
    private String nacosNamespace;


    private final GatewayRateLimitProperties rateLimitProperties;

    public SentinelGatewayConfig(GatewayRateLimitProperties rateLimitProperties) {
        this.rateLimitProperties = rateLimitProperties;
    }

    @PostConstruct
    public void init() {
        // 自查修复（2026-10-15）：批次六的插入曾把下面四步吞进 attachNacosDataSourceIfConfigured
        // 且该方法在未配置 data-id（默认部署）时提前 return——默认部署下限流规则/分组/BlockHandler
        // 全部不再注册。现恢复为 init 依序执行四步，attach 只负责可选数据源挂接。
        initBlockHandler();
        attachNacosDataSourceIfConfigured();
        if (!rateLimitProperties.isEnabled()) {
            return;
        }
        initCustomApis();
        initGatewayRules();
    }

    private void attachNacosDataSourceIfConfigured() {
        if (gatewayRulesDataId == null || gatewayRulesDataId.isBlank() || nacosServerAddr == null || nacosServerAddr.isBlank()) {
            return;
        }
        try {
            com.fasterxml.jackson.core.type.TypeReference<java.util.List<com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayFlowRule>> ruleType =
                    new com.fasterxml.jackson.core.type.TypeReference<>() {
                    };
            // 必须用 Properties 构造并带上配置中心同源凭据：裸 serverAddr 构造的
            // NacosDataSource 客户端无鉴权，在开启 auth 的集群 Nacos 上取配置会持续
            // 403 'user not found!'——挂接看似成功、规则永远为空（2026-10-15 线上实测）。
            java.util.Properties nacosProps = new java.util.Properties();
            nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.SERVER_ADDR, nacosServerAddr);
            if (nacosUsername != null && !nacosUsername.isBlank()) {
                nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.USERNAME, nacosUsername);
            }
            if (nacosPassword != null && !nacosPassword.isBlank()) {
                nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.PASSWORD, nacosPassword);
            }
            if (nacosNamespace != null && !nacosNamespace.isBlank()) {
                nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.NAMESPACE, nacosNamespace);
            }
            // GatewayRuleManager 的 property 类型是 Set<GatewayFlowRule>
            com.alibaba.csp.sentinel.datasource.nacos.NacosDataSource<java.util.Set<com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayFlowRule>> source =
                    new com.alibaba.csp.sentinel.datasource.nacos.NacosDataSource<>(
                            nacosProps, nacosGroup, gatewayRulesDataId,
                            json -> {
                                try {
                                    return new java.util.HashSet<>(new com.fasterxml.jackson.databind.ObjectMapper()
                                            .readValue(json == null ? "[]" : json, ruleType));
                                } catch (com.fasterxml.jackson.core.JsonProcessingException parseError) {
                                    log.warn("网关流控规则 JSON 解析失败，忽略本次更新 dataId={}", gatewayRulesDataId, parseError);
                                    return java.util.Collections.emptySet();
                                }
                            });
            com.alibaba.csp.sentinel.adapter.gateway.common.rule.GatewayRuleManager.register2Property(source.getProperty());
            log.info("Sentinel 网关流控规则已挂接 Nacos 数据源 dataId={}", gatewayRulesDataId);
        } catch (Exception e) {
            log.warn("网关流控 Nacos 数据源挂接失败，回退代码兜底规则 dataId={}", gatewayRulesDataId, e);
        }
    }

    private void initCustomApis() {
        Set<ApiDefinition> definitions = new HashSet<>();

        Set<ApiPredicateItem> authItems = new HashSet<>();
        authItems.add(exact("/api/account/login"));
        authItems.add(exact("/api/account/register"));
        authItems.add(exact("/api/account/getEmailCode"));
        authItems.add(exact("/api/account/forgetPassword"));
        authItems.add(prefix("/admin-api/account/"));
        definitions.add(new ApiDefinition("auth-sensitive").setPredicateItems(authItems));

        Set<ApiPredicateItem> webItems = new HashSet<>();
        webItems.add(prefix("/api/"));
        definitions.add(new ApiDefinition("web-api").setPredicateItems(webItems));

        Set<ApiPredicateItem> adminItems = new HashSet<>();
        adminItems.add(prefix("/admin-api/"));
        definitions.add(new ApiDefinition("admin-api").setPredicateItems(adminItems));

        GatewayApiDefinitionManager.loadApiDefinitions(definitions);
    }

    private void initGatewayRules() {
        Set<GatewayFlowRule> rules = new HashSet<>();
        double defaultQps = rateLimitProperties.getDefaultQps();
        double authQps = rateLimitProperties.getAuthQps();

        rules.add(apiRule("auth-sensitive", authQps));
        rules.add(apiRule("web-api", defaultQps));
        rules.add(apiRule("admin-api", defaultQps));

        for (String routeId : new String[]{
                "user", "product", "cart", "order", "pay", "coupon",
                "stock", "admin-bff"
        }) {
            rules.add(new GatewayFlowRule(routeId).setCount(defaultQps).setIntervalSec(1));
        }
        GatewayRuleManager.loadRules(rules);
    }

    private void initBlockHandler() {
        BlockRequestHandler blockHandler = (ServerWebExchange exchange, Throwable ex) -> {
            Map<String, Object> body = new HashMap<>();
            body.put("status", "error");
            body.put("code", 429);
            body.put("info", "请求过于频繁，请稍后再试");
            body.put("data", null);
            return ServerResponse.status(HttpStatus.TOO_MANY_REQUESTS)
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body);
        };
        GatewayCallbackManager.setBlockHandler(blockHandler);
    }

    private static GatewayFlowRule apiRule(String apiName, double qps) {
        return new GatewayFlowRule(apiName)
                .setResourceMode(SentinelGatewayConstants.RESOURCE_MODE_CUSTOM_API_NAME)
                .setCount(qps)
                .setIntervalSec(1);
    }

    private static ApiPathPredicateItem exact(String path) {
        return new ApiPathPredicateItem()
                .setPattern(path)
                .setMatchStrategy(SentinelGatewayConstants.URL_MATCH_STRATEGY_EXACT);
    }

    private static ApiPathPredicateItem prefix(String path) {
        return new ApiPathPredicateItem()
                .setPattern(path)
                .setMatchStrategy(SentinelGatewayConstants.URL_MATCH_STRATEGY_PREFIX);
    }
}
