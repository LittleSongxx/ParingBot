package com.smartlect.controller.internal;

import com.smartlect.biz.impl.PayChannel4Mock;
import com.smartlect.biz.PayAttemptService;
import com.smartlect.security.MockPaymentSignatureVerifier;
import com.fasterxml.jackson.databind.JsonNode;
import com.smartlect.security.DelegatedUserIdentity;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import jakarta.annotation.Resource;

/** Covered by the common InternalApiAuthFilter; no public mock callback is registered. */
@RestController
@RequestMapping("/internal/pay/mock")
@ConditionalOnProperty(name = "smartlect.payment.mode", havingValue = "mock", matchIfMissing = false)
public class MockPaymentController extends ABaseController {
    private final PayChannel4Mock channel;
    private final MockPaymentSignatureVerifier signatureVerifier;
    @Resource
    private PayAttemptService attempts;

    public MockPaymentController(PayChannel4Mock channel, MockPaymentSignatureVerifier signatureVerifier) {
        this.channel = channel;
        this.signatureVerifier = signatureVerifier;
    }

    @PostMapping("/complete")
    public ResponseVO<PayChannel4Mock.PaymentResult> complete(
            @RequestBody CompletePayment request,
            @RequestHeader(value = "X-Mock-Pay-Timestamp", required = false) String timestamp,
            @RequestHeader(value = "X-Mock-Pay-Nonce", required = false) String nonce,
            @RequestHeader(value = "X-Mock-Pay-Signature", required = false) String signature) {
        String payOrderId = request == null ? null : request.payOrderId();
        Long expectedAmountCents = request == null ? null : request.expectedAmountCents();
        signatureVerifier.verify(payOrderId, expectedAmountCents, timestamp, nonce, signature);
        String userId = DelegatedUserIdentity.require();
        return getSuccessResponseVO(channel.completePayment(userId, payOrderId, expectedAmountCents));
    }

    @PostMapping("/decline")
    public ResponseVO<PayAttemptService.Attempt> decline(@RequestBody JsonNode body) {
        return getSuccessResponseVO(attempts.decline(DelegatedUserIdentity.require(), PayAttemptService.parse(body)));
    }

    @PostMapping("/attempt")
    public ResponseVO<PayAttemptService.Attempt> attempt(@RequestBody JsonNode body) {
        return getSuccessResponseVO(attempts.get(DelegatedUserIdentity.require(), PayAttemptService.parse(body)));
    }

    public record CompletePayment(String payOrderId, Long expectedAmountCents) { }
}
