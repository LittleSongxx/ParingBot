package com.smartlect.security;

import com.smartlect.component.RedisComponent;
import com.smartlect.exception.HttpBusinessException;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.concurrent.TimeUnit;

/**
 * Mock 支付完成接口的签名校验（ADR-0009）。
 *
 * <p>内部令牌只证明“调用方在内部网络里”，不能证明请求体没被替换、也不能阻止同一个请求被重放。
 * 这里加一层 HMAC：签名覆盖方法、路径、支付单号、期望金额、时间戳和随机串；时间窗默认 300 秒，
 * nonce 在 Redis 里 SETNX 一次，重放直接 409。签名开关默认开启，本地密钥由 bootstrap 生成；
 * 生产环境如果仍是默认密钥或长度不足 32，启动失败而不是静默降级。</p>
 */
@Component
public class MockPaymentSignatureVerifier {

    static final String DEFAULT_SECRET = "smartlect-dev-mock-pay-secret";
    static final String COMPLETE_PATH = "/internal/pay/mock/complete";
    private static final String NONCE_PREFIX = "smartlect:pay:mock:nonce:";

    @Value("${smartlect.payment.mock-signature.enabled:true}")
    private boolean enabled;

    @Value("${smartlect.payment.mock-signature.secret:" + DEFAULT_SECRET + "}")
    private String secret;

    @Value("${smartlect.payment.mock-signature.ttl-seconds:300}")
    private long ttlSeconds;

    @Value("${smartlect.payment.mode:mock}")
    private String paymentMode;

    @Resource
    private RedisComponent redisComponent;

    @Resource
    private Environment environment;

    @PostConstruct
    void validateConfiguration() {
        if (!enabled || !"mock".equalsIgnoreCase(paymentMode)) {
            return;
        }
        boolean production = Arrays.stream(environment.getActiveProfiles())
                .anyMatch(profile -> "prod".equals(profile) || "production".equals(profile))
                || environment.getProperty("smartlect.production-ready", Boolean.class, false);
        if (production && (secret == null || secret.length() < 32 || DEFAULT_SECRET.equals(secret))) {
            throw new IllegalStateException(
                    "生产环境必须设置 SMARTLECT_MOCK_PAY_SECRET（至少 32 字节，不能使用开发默认值）");
        }
        ttlSeconds = Math.max(30, Math.min(ttlSeconds, 900));
    }

    /**
     * @throws HttpBusinessException 401 签名/时间戳无效，409 nonce 重放，503 防重放存储不可用
     */
    public void verify(String payOrderId, Long expectedAmountCents,
                       String timestamp, String nonce, String signature) {
        if (!enabled) {
            return;
        }
        if (payOrderId == null || payOrderId.isBlank() || timestamp == null || nonce == null
                || signature == null || nonce.length() < 8 || nonce.length() > 64
                || !nonce.matches("[A-Za-z0-9_-]+")) {
            throw invalid();
        }
        long signedAt;
        try {
            signedAt = Long.parseLong(timestamp);
        } catch (NumberFormatException ex) {
            throw invalid();
        }
        if (Math.abs(System.currentTimeMillis() / 1000 - signedAt) > ttlSeconds) {
            throw invalid();
        }
        String amount = expectedAmountCents == null ? "" : expectedAmountCents.toString();
        String canonical = "POST\n" + COMPLETE_PATH + "\n" + payOrderId + "\n" + amount + "\n"
                + timestamp + "\n" + nonce;
        String expected = hmacHex(canonical);
        if (!MessageDigest.isEqual(expected.getBytes(StandardCharsets.US_ASCII),
                signature.toLowerCase().getBytes(StandardCharsets.US_ASCII))) {
            throw invalid();
        }
        boolean fresh;
        try {
            fresh = redisComponent.setIfAbsent(NONCE_PREFIX + nonce, payOrderId,
                    Math.max(ttlSeconds * 2, 600), TimeUnit.SECONDS);
        } catch (RuntimeException ex) {
            throw new HttpBusinessException(503, "MOCK_PAY_REPLAY_GUARD_UNAVAILABLE");
        }
        if (!fresh) {
            throw new HttpBusinessException(409, "MOCK_PAY_REQUEST_REPLAYED");
        }
    }

    private String hmacHex(String canonical) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return HexFormat.of().formatHex(mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("Mock 支付签名初始化失败", ex);
        }
    }

    private HttpBusinessException invalid() {
        return new HttpBusinessException(401, "MOCK_PAY_SIGNATURE_INVALID");
    }
}
