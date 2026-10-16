package com.smartlect.interceptor;

import com.smartlect.metrics.SmartlectMetrics;
import lombok.extern.slf4j.Slf4j;
import org.apache.ibatis.cache.CacheKey;
import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Signature;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;


/**
 * 慢 SQL 观测：超过阈值记一条 WARN 并累加指标，不改变执行结果。
 *
 * <p>只看 mapperId / 耗时 / traceId / SQL 骨架，<b>不打印参数值</b>——订单、地址、手机号
 * 都在这条链路上，日志里留参数等于把 PII 落盘（脱敏转换器只覆盖日志消息里的已知模式，
 * 覆盖不了任意 SQL 参数）。要定位具体值请用 traceId 去查业务日志。</p>
 *
 * <p>阈值 {@code smartlect.sql.slow-threshold-ms}（默认 200ms）。为什么是 200：本地/演示库
 * 在空载下 95 分位都在 10ms 内，200ms 已经意味着"扫描量或锁等待异常"，不会日常刷屏。</p>
 */
@Slf4j
@Component
@Intercepts({
        @Signature(type = Executor.class, method = "query",
                args = {MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class}),
        @Signature(type = Executor.class, method = "query",
                args = {MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class,
                        CacheKey.class, BoundSql.class}),
        @Signature(type = Executor.class, method = "update",
                args = {MappedStatement.class, Object.class})
})
public class SlowSqlInterceptor implements Interceptor {

    @Value("${smartlect.sql.slow-threshold-ms:200}")
    private long slowThresholdMs = 200L;

    private final SmartlectMetrics metrics;

    public SlowSqlInterceptor(SmartlectMetrics metrics) {
        this.metrics = metrics;
    }

    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        long startedAt = System.nanoTime();
        try {
            return invocation.proceed();
        } finally {
            long costMs = (System.nanoTime() - startedAt) / 1_000_000L;
            if (costMs >= slowThresholdMs) {
                MappedStatement statement = (MappedStatement) invocation.getArgs()[0];
                metrics.slowSql(statement.getId());
                log.warn("慢 SQL {}ms（阈值 {}ms） mapperId={} traceId={} sql={}",
                        costMs, slowThresholdMs, statement.getId(), MDC.get("traceId"),
                        summarize(statement, invocation.getArgs().length > 1 ? invocation.getArgs()[1] : null));
            }
        }
    }

    /** SQL 骨架：折叠空白 + 截断。占位符保留（?），参数值一律不进日志。 */
    static String summarize(MappedStatement statement, Object parameter) {
        String sql;
        try {
            BoundSql boundSql = statement.getBoundSql(parameter);
            sql = boundSql == null ? "" : boundSql.getSql();
        } catch (RuntimeException ex) {
            sql = "<boundSql unavailable: " + ex.getClass().getSimpleName() + ">";
        }
        String collapsed = sql == null ? "" : sql.replaceAll("\\s+", " ").trim();
        return collapsed.length() > 240 ? collapsed.substring(0, 240) + "…" : collapsed;
    }

    /** 仅用于单测断言：暴露当前阈值。 */
    long slowThresholdMs() {
        return slowThresholdMs;
    }
}
