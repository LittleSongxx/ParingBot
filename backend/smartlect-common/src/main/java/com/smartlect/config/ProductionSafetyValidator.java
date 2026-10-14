package com.smartlect.config;

import com.smartlect.utils.StringTools;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class ProductionSafetyValidator {

    private static final Logger log = LoggerFactory.getLogger(ProductionSafetyValidator.class);
    private static final String WEAK_INTERNAL = "your-token";
    private static final String WEAK_ADMIN_PWD = "admin123456";
    private static final int MIN_TOKEN_LENGTH = 24;

    @Value("${smartlect.production-ready:false}")
    private boolean productionReady;

    private final org.springframework.core.env.Environment environment;

    // ADR-0022：prod profile 自动启用校验（忘设开关的生产部署不再裸奔）；本地默认仍仅告警
    public ProductionSafetyValidator(Environment environment) {
        this.environment = environment;
    }

    private boolean enforced() {
        if (productionReady) {
            return true;
        }
        String[] active = environment.getActiveProfiles();
        for (String profile : active) {
            if ("prod".equals(profile) || "production".equals(profile)) {
                return true;
            }
        }
        return false;
    }

    @Value("${smartlect.internal.token:}")
    private String internalToken;

    @Value("${smartlect.internal.ops-token:}")
    private String internalOpsToken;

    @Value("${admin.password:}")
    private String adminPassword;

    @Value("${smartlect.dev-login-bypass:false}")
    private boolean devLoginBypass;

    @Value("${project.folder:}")
    private String projectFolder;

    @Value("${spring.datasource.username:}")
    private String databaseUsername;

    @Value("${spring.datasource.password:}")
    private String databasePassword;

    @Value("${spring.flyway.enabled:true}")
    private boolean flywayEnabled;

    @Value("${spring.flyway.user:}")
    private String flywayUsername;

    @Value("${spring.flyway.password:}")
    private String flywayPassword;

    @PostConstruct
    public void validate() {
        if (!enforced()) {
            log.warn("smartlect.production-ready=false：当前为开发/联调模式，上线前请设为 true 并配置强密钥");
            return;
        }
        StringBuilder errors = new StringBuilder();
        // ADR-0022：弱值检查升级——除已知字面量外，长度下限 24（内部/运维令牌均为 48-hex 运行时生成）
        if (StringTools.isEmpty(internalToken)
                || WEAK_INTERNAL.equals(internalToken)
                || internalToken.length() < MIN_TOKEN_LENGTH) {
            errors.append("SMARTLECT_INTERNAL_TOKEN 未设置、过弱或长度不足 " + MIN_TOKEN_LENGTH + "; ");
        }
        if (StringTools.isEmpty(internalOpsToken)
                || WEAK_INTERNAL.equals(internalOpsToken)
                || internalOpsToken.equals(internalToken)
                || internalOpsToken.length() < MIN_TOKEN_LENGTH) {
            errors.append("SMARTLECT_INTERNAL_OPS_TOKEN 未设置、过弱、长度不足或与内部调用令牌复用; ");
        }
        if (StringTools.isEmpty(adminPassword) || WEAK_ADMIN_PWD.equals(adminPassword)) {
            errors.append("ADMIN_PASSWORD 未设置或仍为默认 admin123456; ");
        }
        if (StringTools.isEmpty(databaseUsername)
                || "root".equalsIgnoreCase(databaseUsername)
                || StringTools.isEmpty(databasePassword)
                || "your-password".equals(databasePassword)) {
            errors.append("MYSQL_USER/MYSQL_PASSWORD 未设置或业务服务仍在使用 root/开发默认凭据; ");
        }
        if (flywayEnabled
                && (StringTools.isEmpty(flywayUsername)
                || "root".equalsIgnoreCase(flywayUsername)
                || flywayUsername.equalsIgnoreCase(databaseUsername)
                || StringTools.isEmpty(flywayPassword)
                || flywayPassword.equals(databasePassword))) {
            errors.append("FLYWAY_USER/FLYWAY_PASSWORD 未设置或与业务运行身份复用; ");
        }
        if (devLoginBypass || System.getProperty("dev") != null) {
            errors.append("禁止生产开启 smartlect.dev-login-bypass 或 -Ddev; ");
        }
        if (StringTools.isEmpty(projectFolder) || projectFolder.contains("./data")) {
            log.warn("生产建议将 PROJECT_FOLDER 指向持久化磁盘目录，当前={}", projectFolder);
        }
        if (errors.length() > 0) {
            throw new IllegalStateException("生产就绪校验失败: " + errors);
        }
        log.info("生产就绪校验通过");
    }
}
