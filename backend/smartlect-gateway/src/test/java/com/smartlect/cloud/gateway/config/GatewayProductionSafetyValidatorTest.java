package com.smartlect.cloud.gateway.config;

import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class GatewayProductionSafetyValidatorTest {

    @Test
    void productionRejectsWeakInternalToken() {
        GatewayProductionSafetyValidator validator = validator(true, "127.0.0.1");
        ReflectionTestUtils.setField(validator, "internalToken", "");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void productionRejectsWildcardBindWhenActuatorExposesPrometheus() {
        GatewayProductionSafetyValidator validator = validator(true, "0.0.0.0");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void emptyBindAddressCountsAsWildcard() {
        GatewayProductionSafetyValidator validator = validator(true, "");

        assertThrows(IllegalStateException.class, validator::validate);
    }

    @Test
    void wildcardBindIsAcceptedWhenExplicitlyAcknowledged() {
        GatewayProductionSafetyValidator validator = validator(true, "0.0.0.0");
        ReflectionTestUtils.setField(validator, "allowWildcardBind", true);

        assertDoesNotThrow(validator::validate);
    }

    @Test
    void loopbackBindWithPrometheusIsAllowed() {
        assertDoesNotThrow(() -> validator(true, "127.0.0.1").validate());
    }

    @Test
    void developmentModeSkipsValidation() {
        assertDoesNotThrow(() -> validator(false, "0.0.0.0").validate());
    }

    private static GatewayProductionSafetyValidator validator(boolean productionReady, String address) {
        GatewayProductionSafetyValidator validator = new GatewayProductionSafetyValidator();
        ReflectionTestUtils.setField(validator, "productionReady", productionReady);
        ReflectionTestUtils.setField(validator, "internalToken", "internal-secret-0123456789abcdef");
        ReflectionTestUtils.setField(validator, "serverAddress", address);
        ReflectionTestUtils.setField(validator, "actuatorExposure", "health,info,prometheus");
        ReflectionTestUtils.setField(validator, "allowWildcardBind", false);
        return validator;
    }
}
