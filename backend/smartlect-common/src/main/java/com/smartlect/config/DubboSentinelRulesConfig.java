package com.smartlect.config;

import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRule;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
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

    @PostConstruct
    public void init() {
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
        log.info("已加载 Feign Sentinel 熔断规则 {} 条", rules.size());
    }
}
