package com.smartlect.api.dubbo;

import com.smartlect.constants.InternalApiHeaders;
import org.apache.dubbo.common.constants.CommonConstants;
import org.apache.dubbo.common.extension.Activate;
import org.apache.dubbo.rpc.Filter;
import org.apache.dubbo.rpc.Invocation;
import org.apache.dubbo.rpc.Invoker;
import org.apache.dubbo.rpc.Result;
import org.apache.dubbo.rpc.RpcException;

import java.security.MessageDigest;

/**
 * Dubbo 内部调用鉴权：consumer 侧附加 X-Internal-Token attachment，provider 侧
 * 常量时间比较校验——与 HTTP 通道的 InternalApiAuthFilter 同一令牌、同一语义
 * （未配置一律拒绝，fail-closed）。
 */
@Activate(group = {CommonConstants.CONSUMER, CommonConstants.PROVIDER})
public class DubboInternalAuthFilter implements Filter {

    private static final String TOKEN_KEY = InternalApiHeaders.INTERNAL_TOKEN;

    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        String side = invoker.getUrl().getParameter(CommonConstants.SIDE_KEY);
        if (CommonConstants.PROVIDER.equals(side)) {
            String incomingTrace = invocation.getAttachment("X-Trace-Id");
            if (incomingTrace != null && !incomingTrace.isBlank()) {
                org.slf4j.MDC.put("traceId", incomingTrace);
            }
            String provided = invocation.getAttachment(TOKEN_KEY);
            String expected = TokenHolder.get();
            if (expected == null || expected.isBlank()
                    || provided == null || !MessageDigest.isEqual(
                            expected.getBytes(java.nio.charset.StandardCharsets.UTF_8),
                            provided.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
                throw new RpcException(RpcException.FORBIDDEN_EXCEPTION,
                        "非法内部 Dubbo 调用: " + invocation.getServiceName());
            }
            return invoker.invoke(invocation);
        }
        // 直接写 invocation attachment：RpcContext clientAttachment 在自定义 Filter 与
        // ConsumerContextFilter 的执行顺序上存在被覆盖的时序问题（实测丢附件）。
        String token = TokenHolder.get();
        if (token != null && !token.isBlank()) {
            invocation.setAttachment(TOKEN_KEY, token);
        }
        // W3C traceparent 链路延续（替代原 FeignTraceInterceptor 的 X-Trace-Id）
        String traceId = org.slf4j.MDC.get("traceId");
        if (traceId != null && !traceId.isBlank()) {
            invocation.setAttachment("X-Trace-Id", traceId);
        }
        return invoker.invoke(invocation);
    }

    /** 由 Spring 配置类注入实际令牌（SPI Filter 非 Spring 托管，走静态桥）。 */
    public static final class TokenHolder {
        private static volatile String token;

        public static void set(String value) {
            token = value;
        }

        public static String get() {
            return token;
        }
    }
}
