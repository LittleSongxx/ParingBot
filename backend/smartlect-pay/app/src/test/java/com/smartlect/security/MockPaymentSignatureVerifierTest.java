package com.smartlect.security;

import com.smartlect.component.RedisComponent;
import com.smartlect.exception.HttpBusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MockPaymentSignatureVerifierTest {

    private static final String SECRET = "0123456789abcdef0123456789abcdef";

    @Mock
    private RedisComponent redisComponent;

    private MockPaymentSignatureVerifier verifier;

    @BeforeEach
    void setUp() {
        verifier = new MockPaymentSignatureVerifier();
        ReflectionTestUtils.setField(verifier, "enabled", true);
        ReflectionTestUtils.setField(verifier, "secret", SECRET);
        ReflectionTestUtils.setField(verifier, "ttlSeconds", 300L);
        ReflectionTestUtils.setField(verifier, "redisComponent", redisComponent);
    }

    @Test
    void acceptsValidSignatureAndConsumesNonce() {
        long now = System.currentTimeMillis() / 1000;
        when(redisComponent.setIfAbsent(eq("smartlect:pay:mock:nonce:nonce-1234"), eq("pay-1"),
                anyLong(), eq(TimeUnit.SECONDS))).thenReturn(true);

        assertDoesNotThrow(() -> verifier.verify("pay-1", 9000L, String.valueOf(now),
                "nonce-1234", sign("pay-1", 9000L, now, "nonce-1234")));
    }

    @Test
    void rejectsTamperedAmountAndExpiredTimestamp() {
        long now = System.currentTimeMillis() / 1000;
        String signature = sign("pay-1", 9000L, now, "nonce-1234");
        assertCode(401, () -> verifier.verify("pay-1", 100L, String.valueOf(now), "nonce-1234", signature));
        assertCode(401, () -> verifier.verify("pay-1", 9000L, String.valueOf(now - 301),
                "nonce-1234", sign("pay-1", 9000L, now - 301, "nonce-1234")));
    }

    @Test
    void rejectsReplayedNonce() {
        long now = System.currentTimeMillis() / 1000;
        when(redisComponent.setIfAbsent(anyString(), anyString(), anyLong(), eq(TimeUnit.SECONDS)))
                .thenReturn(false);
        assertCode(409, () -> verifier.verify("pay-1", 9000L, String.valueOf(now),
                "nonce-1234", sign("pay-1", 9000L, now, "nonce-1234")));
    }

    @Test
    void malformedHeadersFailClosed() {
        long now = System.currentTimeMillis() / 1000;
        assertCode(401, () -> verifier.verify("pay-1", 9000L, String.valueOf(now),
                "short", sign("pay-1", 9000L, now, "short")));
    }

    @Test
    void disabledVerifierDoesNotRequireHeaders() {
        ReflectionTestUtils.setField(verifier, "enabled", false);
        assertDoesNotThrow(() -> verifier.verify("pay-1", 9000L, null, null, null));
    }

    private void assertCode(int expected, Runnable action) {
        HttpBusinessException error = assertThrows(HttpBusinessException.class, action::run);
        assertEquals(expected, error.getHttpStatus());
    }

    private static String sign(String payOrderId, long amountCents, long timestamp, String nonce) {
        String canonical = "POST\n/internal/pay/mock/complete\n" + payOrderId + "\n"
                + amountCents + "\n" + timestamp + "\n" + nonce;
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return HexFormat.of().formatHex(mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
