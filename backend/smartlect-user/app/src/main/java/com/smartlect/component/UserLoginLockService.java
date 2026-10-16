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
 * 与 AdminLoginLockService 同模式（5 次 / 15 分钟），键为**邮箱+IP 组合**——
 * 同一账号换 IP 或同一 IP 撞多个账号都各计各的键，互不串扰（2026-10-17 审计 M3：
 * 原 javadoc 声称"单 IP / 单账号各一维独立的计数"，实现从来只有组合键一档，已按实现改写）。
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
    }

    private void check(String key) {
        if (StringTools.isEmpty(key)) {
            return;
        }
        // Redis 故障时降级为"不锁定"而不是抛 500：锁定是防爆破加固，可用性优先——
        // 2026-10-16 本地实测 Redis 连接重置会把整个登录打成"服务器返回错误"。
        boolean locked;
        try {
            locked = Boolean.TRUE.equals(stringRedisTemplate.hasKey(key + ":locked"));
        } catch (RuntimeException e) {
            log.warn("登录锁定检查降级（Redis 不可用，放行登录）：{}", e.getMessage());
            return;
        }
        if (locked) {
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
        try {
            Long count = stringRedisTemplate.opsForValue().increment(failKey);
            if (count != null && count == 1L) {
                stringRedisTemplate.expire(failKey, LOCK_SECONDS, TimeUnit.SECONDS);
            }
            if (count != null && count >= MAX_FAIL_COUNT) {
                stringRedisTemplate.opsForValue().set(lockKey, "1", LOCK_SECONDS, TimeUnit.SECONDS);
                log.warn("用户登录已锁定 email={}, ip={}, failCount={}", email, ip, count);
            }
        } catch (RuntimeException e) {
            // 计数失败不能把"密码错误"的响应变成 500
            log.warn("登录失败计数未记录（Redis 不可用）：{}", e.getMessage());
        }
    }

    public void clearFailures(String email, String ip) {
        String base = failKey(email, ip);
        if (base == null) {
            return;
        }
        try {
            stringRedisTemplate.delete(base + ":fail");
            stringRedisTemplate.delete(base + ":locked");
        } catch (RuntimeException e) {
            log.warn("登录失败计数清理跳过（Redis 不可用）：{}", e.getMessage());
        }
    }

    private static String failKey(String email, String ip) {
        if (StringTools.isEmpty(email)) {
            return null;
        }
        return Constants.REDIS_KEY_USER_LOGIN_FAIL + email.trim().toLowerCase()
                + ":" + (ip == null ? "unknown" : ip);
    }
}
