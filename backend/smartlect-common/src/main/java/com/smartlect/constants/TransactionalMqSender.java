package com.smartlect.constants;

import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.service.OutboxMessageService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

@Component
@Slf4j
public class TransactionalMqSender {

    @Resource
    private OutboxMessageService outboxMessageService;

    @Resource
    @Qualifier("mqAsyncExecutor")
    private Executor mqAsyncExecutor;

    /**
     * 试投一次，但**不占用调用方线程**。
     *
     * <p>发布确认是同步等待的（默认 5 秒超时）。早先这里在请求线程上直接 tryDispatch，
     * 于是 broker 一有抖动就变成接口延迟：实测 227 次 5 秒确认超时 + 192 次 NACK，
     * 把下单接口的 p95 推到 6.8 秒（2026-10-06 线程转储定位：Tomcat 工作线程停在
     * MqPublisherConfirmHelper.awaitConfirm）。
     *
     * <p>这不改变可靠性语义——outbox 记录已在事务内落库，成败由 OutboxDispatchTask
     * 定时扫描重试兜底。此处只是"尽快送一次"的加速，失败或线程池满都退化为定时重试。
     */
    private void dispatchAsync(long id) {
        try {
            mqAsyncExecutor.execute(() -> {
                try {
                    outboxMessageService.tryDispatch(id);
                } catch (Exception e) {
                    log.warn("Outbox 异步投递失败，等待定时重试 id={}", id, e);
                }
            });
        } catch (RejectedExecutionException e) {
            log.warn("Outbox 异步投递入队被拒，等待定时重试 id={}", id);
        }
    }

    public void sendAfterCommit(String exchange, String routingKey, Object message,
                                String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel) {
        MessageReliabilityLevelEnum level = reliabilityLevel == null
                ? MessageReliabilityLevelEnum.STANDARD : reliabilityLevel;
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            Long id = outboxMessageService.savePending(exchange, routingKey, message, idempotencyKey, level);
            if (id == null) {
                return;
            }
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    dispatchAsync(id);
                }
            });
            return;
        }
        Long id = outboxMessageService.savePending(
                exchange, routingKey, message, idempotencyKey, level);
        if (id == null) {
            return;
        }
        dispatchAsync(id);
    }

    /**
     * 定时投递版本（RocketMQ 任意精度定时消息，取代原 TTL+死信延迟队列）：
     * deliveryExpireAt 为绝对到期时间（epoch 毫秒），事务提交后经 Outbox 投递，
     * 补发时按当前时间折算剩余延迟。
     */
    public void sendAfterCommit(String exchange, String routingKey, Object message,
                                String idempotencyKey, MessageReliabilityLevelEnum reliabilityLevel,
                                Long deliveryExpireAt) {
        MessageReliabilityLevelEnum level = reliabilityLevel == null
                ? MessageReliabilityLevelEnum.STANDARD : reliabilityLevel;
        Long id = outboxMessageService.savePending(
                exchange, routingKey, message, idempotencyKey, level, deliveryExpireAt);
        if (id == null) {
            return;
        }
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    dispatchAsync(id);
                }
            });
            return;
        }
        dispatchAsync(id);
    }

    public void sendAfterCommit(Runnable sendAction) {
        if (sendAction == null) {
            return;
        }
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    sendAction.run();
                }
            });
            return;
        }
        sendAction.run();
    }
}
