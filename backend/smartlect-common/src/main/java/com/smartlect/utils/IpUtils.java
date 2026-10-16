package com.smartlect.utils;

import jakarta.servlet.http.HttpServletRequest;

import java.util.regex.Pattern;

/**
 * 客户端 IP 解析（用于限流与登录锁定的 key）。
 *
 * <p><b>信任模型</b>：只有我方 nginx 会写 `X-Real-IP`（= $remote_addr）与追加
 * `X-Forwarded-For`；因此取 IP 的顺序必须是"先信 X-Real-IP，再取 XFF 的**最后一段**
 * （最近一跳 = 我方 nginx 追加的真实地址）"，绝不能取 XFF 第一段——第一段完全由客户端
 * 控制，能伪造就绕过了 IP 限流与登录锁定（2026-10-16 审计）。</p>
 *
 * <p>并对结果做格式校验：非法值一律回落 remoteAddr，避免把任意字符串写进限流 key 与日志。</p>
 */
public final class IpUtils {

    private static final Pattern IPV4 = Pattern.compile(
            "^((25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.){3}(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)$");
    private static final Pattern IPV6 = Pattern.compile("^[0-9a-fA-F:]{2,45}$");

    private IpUtils() {
    }

    public static String resolveClientIp(HttpServletRequest request) {
        if (request == null) {
            return "unknown";
        }
        String candidate = firstValid(request.getHeader("X-Real-IP"));
        if (candidate == null) {
            String forwarded = request.getHeader("X-Forwarded-For");
            if (forwarded != null && !forwarded.isBlank()) {
                // 取最后一段：这是我方代理追加的那一跳；前面的段是客户端可伪造的
                String[] parts = forwarded.split(",");
                for (int i = parts.length - 1; i >= 0; i--) {
                    String ip = firstValid(parts[i]);
                    if (ip != null) {
                        candidate = ip;
                        break;
                    }
                }
            }
        }
        if (candidate == null) {
            candidate = firstValid(request.getRemoteAddr());
        }
        return candidate == null ? "unknown" : candidate;
    }

    /** 归一化并校验：去空白与 IPv6 方括号；非法（含注入式内容）返回 null。 */
    private static String firstValid(String raw) {
        if (raw == null) {
            return null;
        }
        String value = raw.trim();
        if (value.isEmpty() || "unknown".equalsIgnoreCase(value)) {
            return null;
        }
        if (value.startsWith("[") && value.contains("]")) {
            value = value.substring(1, value.indexOf(']'));
        }
        if (IPV4.matcher(value).matches() || IPV6.matcher(value).matches()) {
            return value;
        }
        return null;
    }
}
