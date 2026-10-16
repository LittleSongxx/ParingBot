package com.smartlect.interceptor;

import com.smartlect.metrics.SmartlectMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.plugin.Invocation;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SlowSqlInterceptorTest {

    private SlowSqlInterceptor interceptor(long thresholdMs) {
        SlowSqlInterceptor interceptor = new SlowSqlInterceptor(
                new SmartlectMetrics(new SimpleMeterRegistry()));
        org.springframework.test.util.ReflectionTestUtils.setField(interceptor, "slowThresholdMs", thresholdMs);
        return interceptor;
    }

    @Test
    void passesThroughResultAndRethrows() throws Throwable {
        SlowSqlInterceptor interceptor = interceptor(10_000L);
        Invocation invocation = mock(Invocation.class);
        when(invocation.proceed()).thenReturn("rows");
        when(invocation.getArgs()).thenReturn(new Object[2]);

        assertEquals("rows", interceptor.intercept(invocation), "慢 SQL 观测不得改变返回值");

        Invocation failing = mock(Invocation.class);
        when(failing.proceed()).thenThrow(new IllegalStateException("db down"));
        when(failing.getArgs()).thenReturn(new Object[2]);
        assertThrows(IllegalStateException.class, () -> interceptor.intercept(failing),
                "异常必须原样抛出（观测不吞错）");
    }

    @Test
    void slowCallIsCountedOnceWithMapperId() throws Throwable {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        SlowSqlInterceptor interceptor = new SlowSqlInterceptor(new SmartlectMetrics(registry));
        org.springframework.test.util.ReflectionTestUtils.setField(interceptor, "slowThresholdMs", 1L);

        MappedStatement statement = mock(MappedStatement.class);
        when(statement.getId()).thenReturn("com.smartlect.mappers.OrderInfoMapper.selectList");
        when(statement.getBoundSql(any())).thenReturn(null);
        Invocation invocation = mock(Invocation.class);
        when(invocation.getArgs()).thenReturn(new Object[]{statement, null});
        when(invocation.proceed()).thenAnswer(inv -> { Thread.sleep(5L); return 1; });

        interceptor.intercept(invocation);

        assertNotNull(registry.find("smartlect_sql_slow_total")
                        .tag("mapper", "com.smartlect.mappers.OrderInfoMapper.selectList").counter(),
                "超过阈值的调用应累加慢 SQL 指标");
    }

    @Test
    void summarizeCollapsesWhitespaceAndKeepsPlaceholdersWithoutValues() {
        MappedStatement statement = mock(MappedStatement.class);
        org.apache.ibatis.mapping.BoundSql boundSql = mock(org.apache.ibatis.mapping.BoundSql.class);
        when(boundSql.getSql()).thenReturn("SELECT *\n   FROM order_info\n WHERE user_id = ?  AND status = ?");
        when(statement.getBoundSql(any())).thenReturn(boundSql);

        String summary = SlowSqlInterceptor.summarize(statement, new Object());

        assertEquals("SELECT * FROM order_info WHERE user_id = ? AND status = ?", summary);
        assertTrue(summary.contains("?"), "占位符保留，参数值不进日志（PII）");
    }
}
