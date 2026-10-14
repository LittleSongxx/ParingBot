package com.smartlect.component;

import com.smartlect.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 用户登录失败锁定（ADR-0022）：5 次失败锁定 15 分钟，成功后清零。 */
@ExtendWith(MockitoExtension.class)
class UserLoginLockServiceTest {

    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;
    @InjectMocks
    private UserLoginLockService service;

    @BeforeEach
    void setUp() {
        lenient().when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
    }

    @Test
    void lockedAccountCannotAttemptLogin() {
        when(stringRedisTemplate.hasKey("smartlect:user:login:a@b.com:1.2.3.4:locked")).thenReturn(true);
        assertThrows(BusinessException.class, () -> service.ensureNotLocked("a@b.com", "1.2.3.4"));
    }

    @Test
    void fifthFailureLocksAccount() {
        when(valueOperations.increment("smartlect:user:login:a@b.com:1.2.3.4:fail")).thenReturn(5L);
        service.recordFailure("a@b.com", "1.2.3.4");
        verify(valueOperations).set(
                anyString(), anyString(), org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.any());
    }

    @Test
    void fewerFailuresDoNotLock() {
        when(valueOperations.increment("smartlect:user:login:a@b.com:1.2.3.4:fail")).thenReturn(4L);
        service.recordFailure("a@b.com", "1.2.3.4");
        // increment 用到了 opsForValue()，只断言 set(锁定写) 未发生
        verify(valueOperations, org.mockito.Mockito.never()).set(
                anyString(), anyString(), org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.any());
    }

    @Test
    void successfulLoginClearsCounters() {
        assertDoesNotThrow(() -> service.clearFailures("a@b.com", "1.2.3.4"));
        verify(stringRedisTemplate).delete("smartlect:user:login:a@b.com:1.2.3.4:fail");
        verify(stringRedisTemplate).delete("smartlect:user:login:a@b.com:1.2.3.4:locked");
    }
}
