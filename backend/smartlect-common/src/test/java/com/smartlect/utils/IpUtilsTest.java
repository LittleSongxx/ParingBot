package com.smartlect.utils;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 客户端 IP 信任模型的回归网（2026-10-16 审计）。
 *
 * <p>核心约束：XFF 第一段由客户端控制，绝不能拿它做限流键或登录锁定键；
 * 只有 nginx 自己写的 X-Real-IP 与它追加的 XFF 最后一跳可信。</p>
 */
class IpUtilsTest {

    @Test
    void forgedFirstForwardedForSegmentIsIgnored() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("10.0.0.9");
        // 攻击者伪造第一段，nginx 在末尾追加真实来源
        request.addHeader("X-Forwarded-For", "6.6.6.6, 203.0.113.7");

        assertEquals("203.0.113.7", IpUtils.resolveClientIp(request));
    }

    @Test
    void realIpHeaderWinsOverForwardedFor() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("10.0.0.9");
        request.addHeader("X-Real-IP", "198.51.100.4");
        request.addHeader("X-Forwarded-For", "6.6.6.6, 203.0.113.7");

        assertEquals("198.51.100.4", IpUtils.resolveClientIp(request));
    }

    @Test
    void lastValidForwardedSegmentIsUsedWhenTrailingHopIsMalformed() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("10.0.0.9");
        request.addHeader("X-Forwarded-For", "6.6.6.6, 203.0.113.7, not-an-ip");

        assertEquals("203.0.113.7", IpUtils.resolveClientIp(request));
    }

    @Test
    void invalidHeadersFallBackToRemoteAddr() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("10.0.0.9");
        request.addHeader("X-Real-IP", "evil; rm -rf /");
        request.addHeader("X-Forwarded-For", "   ");

        assertEquals("10.0.0.9", IpUtils.resolveClientIp(request));
    }

    @Test
    void bracketedIpv6IsNormalized() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("10.0.0.9");
        request.addHeader("X-Real-IP", "[2001:db8::1]");

        assertEquals("2001:db8::1", IpUtils.resolveClientIp(request));
    }

    @Test
    void unknownIsReturnedWhenNothingIsValid() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("unknown");

        assertEquals("unknown", IpUtils.resolveClientIp(request));
        assertEquals("unknown", IpUtils.resolveClientIp(null));
    }
}
