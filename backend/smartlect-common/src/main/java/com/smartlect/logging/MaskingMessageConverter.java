package com.smartlect.logging;

import ch.qos.logback.classic.pattern.MessageConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;

import java.util.regex.Pattern;

/**
 * 日志脱敏转换器（ADR-0021）：手机号/邮箱/身份证在进入日志前打码。
 * 此前全仓无任何脱敏手段，收货地址、邮箱等 PII 直接落日志与 MQ 补偿 payload。
 * 用法：logback 配置注册 conversionWord 后，pattern 用 %maskingMsg 替代 %m。
 */
public class MaskingMessageConverter extends MessageConverter {

    private static final Pattern PHONE = Pattern.compile("(?<!\\d)(1[3-9]\\d)\\d{4}(\\d{4})(?!\\d)");
    private static final Pattern ID_CARD = Pattern.compile("(?<!\\d)(\\d{6})\\d{8}(\\d{4})(?!\\d)");
    private static final Pattern EMAIL = Pattern.compile("([\\w.+-])[^@\\s]{1,}(@[\\w-]+\\.[\\w.]+)");

    @Override
    public String convert(ILoggingEvent event) {
        return mask(event.getFormattedMessage());
    }

    static String mask(String message) {
        if (message == null || message.isEmpty()) {
            return message;
        }
        String masked = PHONE.matcher(message).replaceAll(m ->
                m.group(1) + "****" + m.group(2));
        masked = ID_CARD.matcher(masked).replaceAll(m ->
                m.group(1) + "********" + m.group(2));
        masked = EMAIL.matcher(masked).replaceAll(m ->
                m.group(1) + "***" + m.group(2));
        return masked;
    }
}
