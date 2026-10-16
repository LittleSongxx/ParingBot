package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.exception.BusinessException;
import com.smartlect.exception.PayOrderLifecycleBusyException;
import com.smartlect.redis.RedisUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.concurrent.Callable;
import java.util.concurrent.TimeUnit;

/**
 * 支付订单生命周期的 Redis 标记与互斥锁。
 * <p>从 RedisComponent 拆出来的：支付回调、超时关单、迟到支付退款三条流程会并发操作同一笔支付单，
 * 靠这里的锁和一次性标记保证只有一条生效。这几个键的语义是互相咬合的，放一起才看得出全貌。
 * <p>标记只做"已处理过"的去重，不作为业务状态的依据 —— 状态以数据库为准。
 */
@Component("payOrderRedisComponent")
@Slf4j
public class PayOrderRedisComponent {

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    // 已移除（ADR-0018）：markPayTradeInitiated / isPayTradeInitiated 曾用于支付轮询的过滤闸，
    // 但标记从无生产写入方（死代码），轮询因此永远空转。轮询对账已改为按
    // "创建超过 N 分钟仍待付款"直接查渠道（见 PayOrderTask），不再依赖 Redis 标记。

    public boolean tryMarkPayOrderCloseOnce(String payOrderId) {
		if (StringTools.isEmpty(payOrderId)) {
			return false;
		}
		return setIfAbsent(
				Constants.REDIS_KEY_PAY_ORDER_CLOSE_DONE + payOrderId,
				"1",
				Constants.REDIS_KEY_EXPIRES_DAY,
				TimeUnit.SECONDS);
	}

	public boolean isPayOrderCloseMarked(String payOrderId) {
		if (StringTools.isEmpty(payOrderId)) {
			return false;
		}
		return Boolean.TRUE.equals(stringRedisTemplate.hasKey(
				Constants.REDIS_KEY_PAY_ORDER_CLOSE_DONE + payOrderId));
	}

	// Redisson RLock 取代自研 SETNX+token+Lua 安全解锁：看门狗续期与"仅持有者可解"由框架保证。
	// 保留的框架外语义只有一条——事务提交后才释放锁（afterCompletion 钩子），这是业务正确性要求。
	@Resource
	private RedissonClient redissonClient;

	public void runWithPayOrderLifecycleLock(String payOrderId, Runnable action) {
		runWithPayOrderLifecycleLock(payOrderId, () -> {
			action.run();
			return null;
		});
	}

	public <T> T runWithPayOrderLifecycleLock(String payOrderId, Callable<T> action) {
		if (StringTools.isEmpty(payOrderId)) {
			try {
				return action.call();
			} catch (RuntimeException e) {
				throw e;
			} catch (Exception e) {
				throw new BusinessException("支付订单处理失败", e);
			}
		}
		RLock lock = redissonClient.getLock(Constants.REDIS_KEY_PAY_ORDER_LIFECYCLE_LOCK + payOrderId);
		boolean acquired = false;
		boolean releaseDeferred = false;
		try {
			// 不显式给 leaseTime：走 Redisson 看门狗续期——临界区包含多次远程调用
			// （关单/支付回调：markClosed→closeOrder→解券→回补），累计可能超过 30s；
			// 显式 lease 到期后第二个执行者会进入同一支付单，与仍在执行的第一个并发写状态
			// （2026-10-16 审计 M9）。看门狗在持有者存活期间自动续期，进程死亡即释放。
			long waitMs = Constants.PAY_ORDER_LIFECYCLE_LOCK_WAIT_MS;
			acquired = lock.tryLock(waitMs, TimeUnit.MILLISECONDS);
			if (!acquired) {
				throw new PayOrderLifecycleBusyException();
			}
			return action.call();
		} catch (InterruptedException e) {
			Thread.currentThread().interrupt();
			throw new BusinessException("支付订单处理被中断");
		} catch (RuntimeException e) {
			throw e;
		} catch (Exception e) {
			throw new BusinessException("支付订单处理失败", e);
		} finally {
			if (acquired) {
				releaseDeferred = deferReleaseUntilTransactionCompletion(lock);
				if (!releaseDeferred) {
					releasePayOrderLifecycleLock(lock);
				}
			}
		}
	}

	private void releasePayOrderLifecycleLock(RLock lock) {
		try {
			lock.unlock();
		} catch (RuntimeException e) {
			// The lease still has a TTL. Unlock failure must not turn a committed
			// order transaction into an apparent request failure.
			log.error("支付生命周期锁释放失败，等待租约过期 lockName={}", lock.getName(), e);
		}
	}

	private boolean deferReleaseUntilTransactionCompletion(RLock lock) {
		if (!TransactionSynchronizationManager.isSynchronizationActive()
				|| !TransactionSynchronizationManager.isActualTransactionActive()) {
			return false;
		}
		TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
			@Override
			public void afterCompletion(int status) {
				releasePayOrderLifecycleLock(lock);
			}
		});
		return true;
	}

	public boolean tryMarkLatePaymentRefundOnce(String payOrderId) {
		if (StringTools.isEmpty(payOrderId)) {
			return false;
		}
		// TTL 7 天（原 1 天）：标记过期后同一支付单的重复通知会再次尝试退款；
		// 退款单号改为从 payOrderId 派生后，渠道唯一约束构成第二道防线（2026-10-16 审计 L12）
		return setIfAbsent(
				Constants.REDIS_KEY_PAY_LATE_REFUND_DONE + payOrderId,
				"1",
				7 * Constants.REDIS_KEY_EXPIRES_DAY,
				TimeUnit.SECONDS);
	}

	public void clearLatePaymentRefundMark(String payOrderId) {
		if (StringTools.isEmpty(payOrderId)) {
			return;
		}
		stringRedisTemplate.delete(Constants.REDIS_KEY_PAY_LATE_REFUND_DONE + payOrderId);
	}

	private boolean setIfAbsent(String key, String value, long timeout, TimeUnit unit) {
		return Boolean.TRUE.equals(stringRedisTemplate.opsForValue().setIfAbsent(key, value, timeout, unit));
	}
}
