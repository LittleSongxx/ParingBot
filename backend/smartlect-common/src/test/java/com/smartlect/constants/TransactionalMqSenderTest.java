package com.smartlect.constants;

import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.service.OutboxMessageService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionSynchronizationUtils;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;

@ExtendWith(MockitoExtension.class)
class TransactionalMqSenderTest {

    @Mock
    private OutboxMessageService outboxMessageService;

    @Mock
    private Executor mqAsyncExecutor;

    @InjectMocks
    private TransactionalMqSender sender;

    @BeforeEach
    void runDispatchInline() {
        // 投递已被交给执行器（见 dispatchIsHandedOffToTheExecutor）。测试里让执行器同步执行，
        // 这样"落库在事务内、投递在提交之后"这些原有的断言仍能直接观测到。
        // lenient：回滚用例根本不会走到投递，严格存根会把它判成"多余存根"
        lenient().doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(0)).run();
            return null;
        }).when(mqAsyncExecutor).execute(any(Runnable.class));
    }

    @AfterEach
    void clearTransactionSynchronization() {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void outboxIsSavedInTransactionAndDispatchedOnlyAfterCommit() {
        when(outboxMessageService.savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.HIGH), isNull())).thenReturn(41L);
        TransactionSynchronizationManager.initSynchronization();

        sender.sendAfterCommit(
                "exchange", "route", "payload", "request-key", MessageReliabilityLevelEnum.HIGH, null);

        verify(outboxMessageService).savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.HIGH), isNull());
        verify(outboxMessageService, never()).tryDispatch(any());
        TransactionSynchronizationUtils.invokeAfterCommit(
                TransactionSynchronizationManager.getSynchronizations());
        verify(outboxMessageService).tryDispatch(41L);
    }

    @Test
    void rollbackDoesNotDispatchTheOutboxRecord() {
        when(outboxMessageService.savePending(
                any(), any(), any(), any(), eq(MessageReliabilityLevelEnum.STANDARD), any())).thenReturn(42L);
        TransactionSynchronizationManager.initSynchronization();

        sender.sendAfterCommit("exchange", "route", "payload", "request-key", MessageReliabilityLevelEnum.STANDARD, null);

        TransactionSynchronizationUtils.invokeAfterCompletion(
                TransactionSynchronizationManager.getSynchronizations(),
                TransactionSynchronization.STATUS_ROLLED_BACK);
        verify(outboxMessageService, never()).tryDispatch(any());
    }

    /**
     * 新契约：投递必须交给执行器，不能在请求线程上同步等发布确认。
     * 2026-10-06 实测同步等确认时 broker 抖动把下单 p95 推到 6.8 秒（227 次 5 秒超时），
     * 这里把"不得同步跑"以及"执行器拒绝时不得抛出"固化成断言。
     */
    @Test
    void dispatchIsHandedOffToTheExecutor() {
        when(outboxMessageService.savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.STANDARD), isNull())).thenReturn(44L);
        doThrow(new RejectedExecutionException("queue full"))
                .when(mqAsyncExecutor).execute(any(Runnable.class));

        sender.sendAfterCommit("exchange", "route", "payload", "request-key", MessageReliabilityLevelEnum.STANDARD, null);

        verify(outboxMessageService).savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.STANDARD), isNull());
        verify(outboxMessageService, never()).tryDispatch(any());
    }

    @Test
    void callWithoutTransactionStillPersistsOutboxBeforeDispatch() {
        when(outboxMessageService.savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.HIGH), isNull())).thenReturn(43L);

        sender.sendAfterCommit(
                "exchange", "route", "payload", "request-key", MessageReliabilityLevelEnum.HIGH, null);

        verify(outboxMessageService).savePending(
                eq("exchange"), eq("route"), eq("payload"), eq("request-key"),
                eq(MessageReliabilityLevelEnum.HIGH), isNull());
        verify(outboxMessageService).tryDispatch(43L);
    }
}
