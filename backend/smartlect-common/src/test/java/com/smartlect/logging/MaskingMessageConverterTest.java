package com.smartlect.logging;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 日志脱敏（ADR-0009）：手机号/身份证/邮箱打码，其余内容不动。 */
class MaskingMessageConverterTest {

    @Test
    void masksPhoneIdCardAndEmail() {
        String masked = MaskingMessageConverter.mask(
                "收件人 13812345678，证件 110101199001011234，邮箱 someone@example.com");
        assertTrue(masked.contains("138****5678"));
        assertTrue(masked.contains("110101********1234"));
        assertTrue(masked.contains("s***@example.com"));
        assertFalse(masked.contains("13812345678"));
        assertFalse(masked.contains("someone@example.com"));
    }

    @Test
    void leavesOrdinaryTextAndOrderIdsAlone() {
        String message = "提交订单,payOrderId=2026101400112233a, 订单数量=2, 总金额=99.00";
        assertEquals(message, MaskingMessageConverter.mask(message));
    }
}
