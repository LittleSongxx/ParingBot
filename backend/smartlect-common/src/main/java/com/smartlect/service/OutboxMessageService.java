package com.smartlect.service;

import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.LocalMessageOutbox;

import java.util.List;

public interface OutboxMessageService {

    Long savePending(String exchange, String routingKey, Object payload,
                     String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel);

    /**
     * 定时投递版本：deliveryExpireAt 为绝对到期时间（epoch 毫秒），null 表示立即。
     * dispatch 时按当前时间折算剩余延迟（多次重试后自动收敛为立即投递）。
     */
    Long savePending(String exchange, String routingKey, Object payload,
                     String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel,
                     Long deliveryExpireAt);

    void tryDispatch(Long id);

    int dispatchPendingBatch(int batchSize, int maxRetries);

    int countExhausted();

    List<LocalMessageOutbox> listExhausted(int limit);

    boolean replayExhausted(Long id);
}
