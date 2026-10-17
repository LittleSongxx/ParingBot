package com.smartlect.config;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ProductionSafetyValidatorTest {

    @AfterEach
    void clearDevProperty() {
        System.clearProperty("dev");
    }

    @Test
    void productionRejectsMissingDedicatedOpsToken() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "internalOpsToken", "");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionRejectsReusedInternalToken() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "internalOpsToken", "internal-secret-0123456789abcdef");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionAcceptsIndependentStrongTokens() {
        assertDoesNotThrow(() -> validator(true).validate());
    }

    @Test
    void productionRejectsRootDatabaseIdentity() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "databaseUsername", "root");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionRejectsMissingDatabasePassword() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "databasePassword", "");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionRejectsReusedFlywayIdentity() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "flywayUsername", "smartlect");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionAllowsFlywayToBeDisabledAfterExternalMigration() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "flywayEnabled", false);
        ReflectionTestUtils.setField(validator, "flywayUsername", "");
        ReflectionTestUtils.setField(validator, "flywayPassword", "");

        assertDoesNotThrow(validator::validate);
    }

    @Test
    void developmentModeDoesNotRequireProductionSecrets() {
        assertDoesNotThrow(() -> validator(false).validate());
    }

    @Test
    void prodProfileEnforcesValidationEvenWithoutSwitch() {
        // ADR-0009：忘设 smartlect.production-ready 的 prod 部署不再裸奔
        org.springframework.mock.env.MockEnvironment env = new org.springframework.mock.env.MockEnvironment();
        env.setActiveProfiles("prod");
        ProductionSafetyValidator bare = new ProductionSafetyValidator(env);
        org.junit.jupiter.api.Assertions.assertThrows(IllegalStateException.class, bare::validate);
    }

    @Test
    void shortTokensAreRejectedWhenEnforced() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "internalToken", "short-token");
        org.junit.jupiter.api.Assertions.assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionRejectsWildcardBindWhenActuatorExposesPrometheus() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "serverAddress", "0.0.0.0");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void emptyBindAddressCountsAsWildcard() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "serverAddress", "");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void wildcardBindIsAcceptedWhenExplicitlyAcknowledged() {
        ProductionSafetyValidator validator = validator(true);
        ReflectionTestUtils.setField(validator, "serverAddress", "0.0.0.0");
        ReflectionTestUtils.setField(validator, "allowWildcardBind", true);

        assertDoesNotThrow(validator::validate);
    }

    @Test
    void loopbackBindWithPrometheusIsAllowed() {
        assertDoesNotThrow(() -> validator(true).validate());
    }

    private static ProductionSafetyValidator validator(boolean productionReady) {
        return validator(productionReady, new String[0]);
    }

    private static ProductionSafetyValidator validator(boolean productionReady, String... activeProfiles) {
        org.springframework.mock.env.MockEnvironment env = new org.springframework.mock.env.MockEnvironment();
        env.setActiveProfiles(activeProfiles);
        ProductionSafetyValidator validator = new ProductionSafetyValidator(env);
        ReflectionTestUtils.setField(validator, "productionReady", productionReady);
        ReflectionTestUtils.setField(validator, "internalToken", "internal-secret-0123456789abcdef");
        ReflectionTestUtils.setField(validator, "internalOpsToken", "ops-secret-0123456789abcdef");
        ReflectionTestUtils.setField(validator, "adminPassword", "strong-admin-password");
        ReflectionTestUtils.setField(validator, "devLoginBypass", false);
        ReflectionTestUtils.setField(validator, "projectFolder", "/data/smartlect/upload/");
        ReflectionTestUtils.setField(validator, "databaseUsername", "smartlect");
        ReflectionTestUtils.setField(validator, "databasePassword", "strong-db-password");
        ReflectionTestUtils.setField(validator, "flywayEnabled", true);
        ReflectionTestUtils.setField(validator, "flywayUsername", "smartlect_flyway");
        ReflectionTestUtils.setField(validator, "flywayPassword", "strong-flyway-password");
        // 默认按本地/单机形态：只绑回环，actuator 暴露 prometheus 也不构成风险
        ReflectionTestUtils.setField(validator, "serverAddress", "127.0.0.1");
        ReflectionTestUtils.setField(validator, "actuatorExposure", "health,info,prometheus");
        ReflectionTestUtils.setField(validator, "allowWildcardBind", false);
        return validator;
    }
}
