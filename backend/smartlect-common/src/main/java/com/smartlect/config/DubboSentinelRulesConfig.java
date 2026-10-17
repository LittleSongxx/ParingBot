package com.smartlect.config;

import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRule;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

@Component
@Slf4j
@ConditionalOnClass(DegradeRuleManager.class)
@ConditionalOnProperty(name = "smartlect.sentinel.dubbo-rules-enabled", havingValue = "true", matchIfMissing = true)
public class DubboSentinelRulesConfig {

    @Resource
    private Environment environment;

    // ADR-0009：可选 Nacos 动态数据源——配置 smartlect.sentinel.dubbo-rules-data-id 后，
    // 熔断规则由配置中心热更（JSON 数组，字段同 DegradeRule），代码注册的规则仅作兜底默认。
    @Value("${smartlect.sentinel.dubbo-rules-data-id:}")
    private String dubboRulesDataId;

    @PostConstruct
    public void init() {
        // 自查修复（2026-10-15）：数据源挂接成功后 register2Property 已接管规则，
        // 下方 loadRules 会用内部 property 覆盖掉它——挂接成功时跳过代码兜底规则注册。
        if (attachNacosDataSourceIfConfigured()) {
            return;
        }
        registerCodeFallbackRules();
    }

    private boolean attachNacosDataSourceIfConfigured() {
        if (!dubboRulesDataId.isBlank()) {
            try {
                String serverAddr = environment.getProperty("spring.cloud.nacos.config.server-addr", "");
                String group = environment.getProperty("spring.cloud.nacos.config.group", "DEFAULT_GROUP");
                if (!serverAddr.isBlank()) {
                    com.fasterxml.jackson.core.type.TypeReference<List<DegradeRule>> ruleType =
                            new com.fasterxml.jackson.core.type.TypeReference<>() {
                            };
                    // 必须用 Properties 构造并带上配置中心同源凭据：裸 serverAddr 构造的
                    // NacosDataSource 客户端无鉴权，在开启 auth 的集群 Nacos 上取配置会持续
                    // 403 'user not found!'——挂接看似成功、规则永远为空（2026-10-15 线上实测）。
                    java.util.Properties nacosProps = new java.util.Properties();
                    nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.SERVER_ADDR, serverAddr);
                    String username = environment.getProperty("spring.cloud.nacos.config.username", "");
                    String password = environment.getProperty("spring.cloud.nacos.config.password", "");
                    String namespace = environment.getProperty("spring.cloud.nacos.config.namespace", "");
                    if (!username.isBlank()) {
                        nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.USERNAME, username);
                    }
                    if (!password.isBlank()) {
                        nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.PASSWORD, password);
                    }
                    if (!namespace.isBlank()) {
                        nacosProps.put(com.alibaba.nacos.api.PropertyKeyConst.NAMESPACE, namespace);
                    }
                    com.alibaba.csp.sentinel.datasource.nacos.NacosDataSource<List<DegradeRule>> source =
                            new com.alibaba.csp.sentinel.datasource.nacos.NacosDataSource<>(
                                    nacosProps, group, dubboRulesDataId,
                                    json -> {
                                        try {
                                            return new com.fasterxml.jackson.databind.ObjectMapper()
                                                    .readValue(json == null ? "[]" : json, ruleType);
                                        } catch (com.fasterxml.jackson.core.JsonProcessingException parseError) {
                                            log.warn("Sentinel 规则 JSON 解析失败，忽略本次更新 dataId={}", dubboRulesDataId, parseError);
                                            return java.util.Collections.emptyList();
                                        }
                                    });
                    com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager.register2Property(source.getProperty());
                    log.info("Sentinel Dubbo 熔断规则已挂接 Nacos 数据源 dataId={}, group={}", dubboRulesDataId, group);
                    return true;
                }
            } catch (Exception e) {
                log.warn("Nacos 数据源挂接失败，回退代码兜底规则 dataId={}", dubboRulesDataId, e);
            }
        }
        return false;
    }

    private void registerCodeFallbackRules() {
        List<DegradeRule> rules = new ArrayList<>();
        for (String resource : new String[]{
                "com.smartlect.api.dubbo.StockDubboService.getStock",
                "com.smartlect.api.dubbo.StockDubboService.changeStock",
                "com.smartlect.api.dubbo.StockDubboService.changeStockBatch",
                "com.smartlect.api.dubbo.StockDubboService.setStock",
                "com.smartlect.api.dubbo.StockDubboService.totalByProduct",
                "com.smartlect.api.dubbo.CouponDubboService.validateAndLock",
                "com.smartlect.api.dubbo.CouponDubboService.getCoupon",
                "com.smartlect.api.dubbo.CouponDubboService.getCouponBrief",
                "com.smartlect.api.dubbo.CouponDubboService.getUserCoupon",
                "com.smartlect.api.dubbo.CouponDubboService.changeUserCouponStatus",
                "com.smartlect.api.dubbo.CouponDubboService.createUserCoupon",
                "com.smartlect.api.dubbo.CouponDubboService.deductStock",
                "com.smartlect.api.dubbo.ProductDubboService.snapshotBatch",
                "com.smartlect.api.dubbo.ProductDubboService.defaultSku",
                "com.smartlect.api.dubbo.ProductDubboService.increaseSales",
                "com.smartlect.api.dubbo.UserDubboService.getAddress"
        }) {
            DegradeRule rule = new DegradeRule(resource)
                    .setGrade(RuleConstant.DEGRADE_GRADE_EXCEPTION_RATIO)
                    .setCount(0.5)
                    .setTimeWindow(10)
                    .setMinRequestAmount(10)
                    .setStatIntervalMs(10000);
            rules.add(rule);
        }
        DegradeRuleManager.loadRules(rules);
        log.info("已加载 Dubbo Sentinel 熔断规则 {} 条", rules.size());
    }
}
