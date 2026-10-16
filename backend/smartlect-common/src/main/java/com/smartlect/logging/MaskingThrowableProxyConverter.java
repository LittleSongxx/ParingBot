package com.smartlect.logging;

import ch.qos.logback.classic.pattern.ThrowableProxyConverter;
import ch.qos.logback.classic.spi.IThrowableProxy;

/**
 * 异常堆栈脱敏：把 %ex 换成"逐层打码"的版本。
 *
 * <p>为什么需要（2026-10-16 审计）：{@link MaskingMessageConverter} 只作用于日志消息文本
 * （%maskingMsg），而 Logback 自动追加的异常堆栈（%ex）完全不过它——唯一键冲突、
 * SQL 参数、邮箱/手机号都可能随着异常消息落盘。</p>
 *
 * <p>做法：复用 Logback 自己的堆栈渲染（含 cause 链与 suppressed），但在拼接前对每一层的
 * 类名/消息做同一套打码。定位能力不受影响（类名与帧仍在）。</p>
 */
public class MaskingThrowableProxyConverter extends ThrowableProxyConverter {

    @Override
    protected String throwableProxyToString(IThrowableProxy tp) {
        String rendered = super.throwableProxyToString(tp);
        return MaskingMessageConverter.mask(rendered);
    }

    /** 供单测直接验证"类名+消息"这一层的打码行为（不依赖 logback 上下文）。 */
    static String maskLine(String line) {
        return MaskingMessageConverter.mask(line);
    }
}
