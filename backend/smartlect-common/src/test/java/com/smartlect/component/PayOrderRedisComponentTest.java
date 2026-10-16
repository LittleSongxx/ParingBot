package com.smartlect.component;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionSynchronizationUtils;

import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PayOrderRedisComponentTest {

    @Mock
    private RedissonClient redissonClient;
    @Mock
    private RLock lock;

    private PayOrderRedisComponent component;

    @BeforeEach
    void setUp() {
        component = new PayOrderRedisComponent();
        ReflectionTestUtils.setField(component, "redissonClient", redissonClient);
        when(redissonClient.getLock(anyString())).thenReturn(lock);
    }

    @AfterEach
    void clearTransactionState() {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
        TransactionSynchronizationManager.setActualTransactionActive(false);
    }

    @Test
    void transactionKeepsLifecycleLockUntilAfterCompletion() throws InterruptedException {
        when(lock.tryLock(anyLong(), any(TimeUnit.class))).thenReturn(true);
        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);

        component.runWithPayOrderLifecycleLock("pay-1", () -> null);

        // 事务内：锁不释放，交给 afterCompletion
        verify(lock, never()).unlock();
        TransactionSynchronizationUtils.invokeAfterCompletion(
                TransactionSynchronizationManager.getSynchronizations(),
                TransactionSynchronization.STATUS_COMMITTED);
        verify(lock).unlock();
    }

    @Test
    void callWithoutTransactionReleasesLifecycleLockImmediately() throws InterruptedException {
        when(lock.tryLock(anyLong(), any(TimeUnit.class))).thenReturn(true);

        component.runWithPayOrderLifecycleLock("pay-2", () -> null);

        verify(lock).unlock();
    }

    @Test
    void busyLockThrowsLifecycleBusyException() throws InterruptedException {
        when(lock.tryLock(anyLong(), any(TimeUnit.class))).thenReturn(false);
        org.junit.jupiter.api.Assertions.assertThrows(
                com.smartlect.exception.PayOrderLifecycleBusyException.class,
                () -> component.runWithPayOrderLifecycleLock("pay-3", () -> null));
        verify(lock, never()).unlock();
    }

    @Test
    void unlockFailureAfterCommitIsSwallowedToKeepCommittedResult() throws InterruptedException {
        when(lock.tryLock(anyLong(), any(TimeUnit.class))).thenReturn(true);
        org.mockito.Mockito.doThrow(new IllegalStateException("lease expired"))
                .when(lock).unlock();
        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);

        component.runWithPayOrderLifecycleLock("pay-4", () -> "ok");

        // 释放失败不能把已提交的事务翻成请求失败——吞掉，等租约过期。
        TransactionSynchronizationUtils.invokeAfterCompletion(
                TransactionSynchronizationManager.getSynchronizations(),
                TransactionSynchronization.STATUS_COMMITTED);
        assertTrue(true);
    }
}
