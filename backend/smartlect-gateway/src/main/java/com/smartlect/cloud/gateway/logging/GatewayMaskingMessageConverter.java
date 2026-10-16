package com.smartlect.cloud.gateway.logging;

import ch.qos.logback.classic.pattern.MessageConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;

import java.util.regex.Pattern;

/**
 * 网关日志脱敏（网关不依赖 common，故自带一份最小实现，规则与 common 的
 * MaskingMessageConverter 保持一致：手机号 / 邮箱）。
 *
 * <p>2026-10-16 审计：网关此前无任何脱敏，"网关日志不含 PII"只是注释里的说法。</p>
 */
public class GatewayMaskingMessageConverter extends MessageConverter {

    private static final Pattern PHONE = Pattern.compile("(?<!\\d)(1[3-9]\\d)\\d{4}(\\d{4})(?!\\d)");
    private static final Pattern EMAIL = Pattern.compile("([\\w.+-])[^@\\s]{1,}(@[\\w-]+\\.[\\w.]+)");

    @Override
    public String convert(ILoggingEvent event) {
        String message = event.getFormattedMessage();
        if (message == null || message.isEmpty()) {
            return message;
        }
        String masked = PHONE.matcher(message).replaceAll(m -> m.group(1) + "****" + m.group(2));
        return EMAIL.matcher(masked).replaceAll(m -> m.group(1) + "***" + m.group(2));
    }
}
