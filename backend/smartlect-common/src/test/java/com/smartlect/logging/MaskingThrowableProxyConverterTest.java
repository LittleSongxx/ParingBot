package com.smartlect.logging;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/** 异常堆栈脱敏：%ex 默认不过 %maskingMsg，唯一键冲突/SQL 参数会带着 PII 落盘（2026-10-16 审计）。 */
class MaskingThrowableProxyConverterTest {

    @Test
    void masksPhoneEmailAndIdCardInsideStackText() {
        String stack = "java.sql.SQLIntegrityConstraintViolationException: Duplicate entry "
                + "'shopper@smartlect.demo' for key 'uk_user_email'\n"
                + "\tat com.smartlect.biz.UserInfoServiceImpl.register(UserInfoServiceImpl.java:141)\n"
                + "Caused by: java.lang.IllegalStateException: 手机号 13812345678 已绑定";
        String masked = MaskingThrowableProxyConverter.maskLine(stack);

        assertFalse(masked.contains("shopper@smartlect.demo"), "邮箱必须打码");
        assertFalse(masked.contains("13812345678"), "手机号必须打码");
        assertTrue(masked.contains("UserInfoServiceImpl.register"), "定位信息（类名与方法）必须保留");
        assertTrue(masked.contains("SQLIntegrityConstraintViolationException"), "异常类型必须保留");
    }

    @Test
    void keepsPlainTextUnchangedWhenNothingToMask() {
        String text = "Outbox 投递失败 id=1221 key=pay:timeout:20261016";
        assertEquals(text, MaskingThrowableProxyConverter.maskLine(text));
    }
}
