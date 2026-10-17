package com.smartlect.biz;

import com.smartlect.api.dto.IdempotencyReplayAware;
import com.smartlect.api.dto.PostOrderDTO;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.mappers.OrderRequestIdempotencyMapper;
import com.smartlect.metrics.SmartlectMetrics;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.RequestFingerprint;
import org.springframework.stereotype.Service;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.List;
import java.util.function.Supplier;
import java.util.regex.Pattern;

@Service
public class OrderRequestIdempotencyService {

    // 台账事务语义（ADR-0002）：
    // - PROCESSING 插入与 FAILED 收口走 REQUIRES_NEW 独立提交——即使调用方（如秒杀入口）
    //   的外层事务回滚，"请求已受理 / 已失败"仍留痕，同键重放能得到确定性结果而不是凭空重来；
    //   旧实现用默认 REQUIRED 传播，"独立事务"的注释承诺在 @Transactional 调用方下并不成立。
    // - COMPLETED 收口保持参与调用方事务（无外层事务时自动提交）：只有业务真正提交后
    //   响应才可重放，避免"台账已 COMPLETED 而业务回滚"的假成功。
    private final TransactionTemplate ledgerTx;
    private final OrderRequestIdempotencyMapper mapper;
    private final SmartlectMetrics metrics;

    public OrderRequestIdempotencyService(
            PlatformTransactionManager transactionManager,
            OrderRequestIdempotencyMapper mapper,
            SmartlectMetrics metrics) {
        this.ledgerTx = new TransactionTemplate(transactionManager);
        this.ledgerTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        this.mapper = mapper;
        this.metrics = metrics;
    }

    public static final String COMMAND_POST_ORDER = "POST_ORDER";
    public static final String COMMAND_POST_ORDER_V2 = "POST_ORDER_V2";
    public static final String COMMAND_COUPON_RUSH_PREPARE = "COUPON_RUSH_PREPARE";
    public static final String COMMAND_COUPON_RUSH_PAY = "COUPON_RUSH_PAY";
    public static final String COMMAND_COMMERCE_REFUND = "COMMERCE_REFUND";
    public static final String COMMAND_COMMERCE_CANCEL_ORDER = "COMMERCE_CANCEL_ORDER";
    public static final String COMMAND_COMMERCE_CONFIRM_RECEIPT = "COMMERCE_CONFIRM_RECEIPT";

    private static final Pattern KEY_PATTERN = Pattern.compile("[A-Za-z0-9._:-]{16,64}");
    static final long STALE_PROCESSING_MILLIS = 120_000L;

    public <T> T execute(
            String userId,
            String commandType,
            String idempotencyKey,
            Object request,
            Class<T> responseType,
            Supplier<T> command) {
        validateKey(idempotencyKey);
        Object fingerprintRequest = request;
        if (request instanceof PostOrderDTO) {
            ObjectNode payload = JsonUtils.mapper().valueToTree(request);
            // Optional validated touchpoints may disappear or get a new timestamp
            // on retry. They must not change the identity of the purchase itself.
            payload.withArray("orderList").forEach(item -> ((ObjectNode) item).remove(List.of(
                    "recommendationRequestId", "recommendationPosition",
                    "recommendationSource", "recommendationAttributedAt")));
            fingerprintRequest = payload;
        }
        String requestHash = RequestFingerprint.sha256(fingerprintRequest);
        OrderRequestIdempotency newRecord = new OrderRequestIdempotency();
        newRecord.setUserId(userId);
        newRecord.setCommandType(commandType);
        newRecord.setIdempotencyKey(idempotencyKey);
        newRecord.setRequestHash(requestHash);

        boolean acquired;
        try {
            // PROCESSING 插入走 REQUIRES_NEW 独立事务：即使调用方后续回滚，
            // 幂等账本仍留痕（请求已受理），重复请求与 stale 判定都有据可依。
            acquired = Boolean.TRUE.equals(ledgerTx.execute(txStatus ->
                    mapper.insertProcessing(newRecord) == 1));
        } catch (DuplicateKeyException duplicate) {
            // 让唯一约束显式报告一次重放，而不是把插入异常吞成零行影响。
            // （历史注：Seata 时代 ignored-insert 会破坏 after-image 生成；Seata
            // 已随 ADR-0001 移除，此处保留显式重放语义不变。）
            acquired = false;
        }
        if (!acquired) {
            OrderRequestIdempotency existing = mapper.selectForUpdate(
                    userId, commandType, idempotencyKey);
            if (existing == null) {
                throw new HttpBusinessException(409, "请求正在处理中，请稍后重试");
            }
            if (!requestHash.equals(existing.getRequestHash())) {
                metrics.idempotentConflict(commandType, "fingerprint_mismatch");
                throw new HttpBusinessException(409, "同一幂等键不能用于不同请求");
            }
            if ("PROCESSING".equals(existing.getStatus())) {
                if (isStaleProcessing(existing)) {
                    mapper.recordInconclusive(
                            userId,
                            commandType,
                            idempotencyKey,
                            3,
                            Date.from(Instant.now().plusSeconds(3600)),
                            "processing_stale");
                    metrics.idempotentConflict(commandType, "stale_processing");
                    throw new HttpBusinessException(409, "原请求结果正在核对，不能重复执行");
                }
                metrics.idempotentConflict(commandType, "in_flight");
                throw new HttpBusinessException(409, "请求正在处理中，请稍后重试");
            }
            if ("INCONCLUSIVE".equals(existing.getStatus())) {
                metrics.idempotentConflict(commandType, "inconclusive");
                throw new HttpBusinessException(409, "原请求结果正在核对，不能重复执行");
            }
            if ("MANUAL_REVIEW".equals(existing.getStatus())) {
                metrics.idempotentConflict(commandType, "manual_review");
                throw new HttpBusinessException(409, "原请求正在人工复核，不能重复执行");
            }
            if ("FAILED".equals(existing.getStatus())) {
                throw new HttpBusinessException(
                        409,
                        "原请求执行失败：" + storedFailureMessage(existing.getResponseJson()));
            }
            if (!"COMPLETED".equals(existing.getStatus())) {
                throw new HttpBusinessException(409, "幂等请求状态异常，请联系管理员");
            }
            if (existing.getResponseJson() == null || existing.getResponseJson().isBlank()) {
                throw new HttpBusinessException(409, "幂等请求结果缺失，请联系管理员");
            }
            T replay = JsonUtils.parseObject(existing.getResponseJson(), responseType);
            markReplay(replay, true);
            metrics.idempotentReplay(commandType);
            return replay;
        }

        try {
            T response = command.get();
            markReplay(response, false);
            int updated = mapper.markCompleted(
                    userId,
                    commandType,
                    idempotencyKey,
                    JsonUtils.toJson(response));
            if (updated != 1) {
                throw new IllegalStateException("failed to persist idempotent command response");
            }
            return response;
        } catch (RuntimeException ex) {
            // 被拒绝的命令必须把台账行收口为 FAILED，而不是留下一把永久锁。
            // FAILED 收口同样走 REQUIRES_NEW：秒杀入口等 @Transactional 调用方回滚时，
            // 失败结果仍独立提交，同键重放得到"原请求执行失败"而不是从 PROCESSING 从头再来。
            try {
                ledgerTx.executeWithoutResult(txStatus -> mapper.markFailed(
                        userId,
                        commandType,
                        idempotencyKey,
                        JsonUtils.toJson(Map.of("errorMessage", failureMessage(ex)))));
            } catch (RuntimeException ledgerError) {
                ex.addSuppressed(ledgerError);
            }
            throw ex;
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> executeMap(
            String userId,
            String commandType,
            String idempotencyKey,
            Object request,
            Supplier<Map<String, Object>> command) {
        Class<Map<String, Object>> responseType =
                (Class<Map<String, Object>>) (Class<?>) Map.class;
        return execute(
                userId,
                commandType,
                idempotencyKey,
                request,
                responseType,
                () -> new LinkedHashMap<>(command.get()));
    }

    public OrderRequestIdempotency find(
            String userId, String commandType, String idempotencyKey) {
        if (userId == null || commandType == null || idempotencyKey == null) {
            return null;
        }
        return mapper.select(userId, commandType, idempotencyKey);
    }

    public boolean markReconciled(
            String userId,
            String commandType,
            String idempotencyKey,
            String resultMessage) {
        return mapper.markReconciled(
                userId,
                commandType,
                idempotencyKey,
                JsonUtils.toJson(Map.of(
                        "reconciled", true,
                        "resultMessage", resultMessage))) == 1;
    }

    public OrderRequestIdempotency recordInconclusive(
            String userId,
            String commandType,
            String idempotencyKey,
            int maxAttempts,
            int reconcileWindowSeconds,
            String reviewReason) {
        int boundedAttempts = Math.max(1, Math.min(maxAttempts, 100));
        int boundedWindow = Math.max(60, Math.min(reconcileWindowSeconds, 7 * 24 * 3600));
        Date deadline = Date.from(Instant.now().plusSeconds(boundedWindow));
        mapper.recordInconclusive(
                userId,
                commandType,
                idempotencyKey,
                boundedAttempts,
                deadline,
                truncate(reviewReason, 512));
        return mapper.select(userId, commandType, idempotencyKey);
    }

    private static String storedFailureMessage(String responseJson) {
        if (responseJson != null && !responseJson.isBlank()) {
            try {
                Map<?, ?> payload = JsonUtils.parseObject(responseJson, Map.class);
                Object message = payload == null ? null : payload.get("errorMessage");
                if (message != null && !String.valueOf(message).isBlank()) {
                    return String.valueOf(message);
                }
            } catch (RuntimeException ignored) {
                // Legacy or damaged rows still need a deterministic terminal replay.
            }
        }
        return "操作执行失败";
    }

    private static String failureMessage(RuntimeException error) {
        if (error == null || error.getMessage() == null || error.getMessage().isBlank()) {
            return "操作执行失败";
        }
        return error.getMessage().length() > 500
                ? error.getMessage().substring(0, 500)
                : error.getMessage();
    }

    private static String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }

    static boolean isStaleProcessing(OrderRequestIdempotency existing) {
        Date created = existing == null ? null : existing.getCreateTime();
        return created != null
                && Instant.now().toEpochMilli() - created.getTime() >= STALE_PROCESSING_MILLIS;
    }

    public void validateKey(String idempotencyKey) {
        if (idempotencyKey == null || !KEY_PATTERN.matcher(idempotencyKey).matches()) {
            throw new HttpBusinessException(
                    400,
                    "Idempotency-Key 必须为 16-64 位 ASCII 字母、数字或 . _ : -");
        }
    }

    private static void markReplay(Object response, boolean replayed) {
        if (response instanceof IdempotencyReplayAware replayAware) {
            replayAware.setIdempotencyReplayed(replayed);
        } else if (response instanceof Map<?, ?> map) {
            // Growth write controllers return a small map rather than a DTO.
            // Preserve the same replay metadata contract for those endpoints.
            @SuppressWarnings("unchecked")
            Map<Object, Object> mutable = (Map<Object, Object>) map;
            mutable.put("idempotencyReplayed", replayed);
        }
    }
}
