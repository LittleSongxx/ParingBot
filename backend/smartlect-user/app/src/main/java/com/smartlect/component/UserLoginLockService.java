package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.exception.BusinessException;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.concurrent.TimeUnit;

/**
 * 普通用户登录失败锁定（ADR-0022）：此前仅管理端有锁定，普通登录可被枚举爆破。
 * 与 AdminLoginLockService 同模式（5 次 / 15 分钟），键按 邮箱+IP 双维度——
 * 单 IP 撞多账号与单账号多 IP 都会被各自维度收敛。
 */
@Service
@Slf4j
public class UserLoginLockService {

    private static final int MAX_FAIL_COUNT = 5;
    private static final long LOCK_SECONDS = 15 * 60L;

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    public void ensureNotLocked(String email, String ip) {
        check(failKey(email, ip));
        check(lockKey(email, ip));
    }

    private void check(String key) {
        if (!StringTools.isEmpty(key)
                && Boolean.TRUE.equals(stringRedisTemplate.hasKey(key + ":locked"))) {
            throw new BusinessException("登录失败次数过多，请15分钟后再试");
        }
    }

    public void recordFailure(String email, String ip) {
        String base = failKey(email, ip);
        if (base == null) {
            return;
        }
        String failKey = base + ":fail";
        String lockKey = base + ":locked";
        Long count = stringRedisTemplate.opsForValue().increment(failKey);
        if (count != null && count == 1L) {
            stringRedisTemplate.expire(failKey, LOCK_SECONDS, TimeUnit.SECONDS);
        }
        if (count != null && count >= MAX_FAIL_COUNT) {
            stringRedisTemplate.opsForValue().set(lockKey, "1", LOCK_SECONDS, TimeUnit.SECONDS);
            log.warn("用户登录已锁定 email={}, ip={}, failCount={}", email, ip, count);
        }
    }

    public void clearFailures(String email, String ip) {
        String base = failKey(email, ip);
        if (base == null) {
            return;
        }
        stringRedisTemplate.delete(base + ":fail");
        stringRedisTemplate.delete(base + ":locked");
    }

    private static String failKey(String email, String ip) {
        if (StringTools.isEmpty(email)) {
            return null;
        }
        return Constants.REDIS_KEY_USER_LOGIN_FAIL + email.trim().toLowerCase()
                + ":" + (ip == null ? "unknown" : ip);
    }

    private static String lockKey(String email, String ip) {
        return failKey(email, ip);
    }
}
