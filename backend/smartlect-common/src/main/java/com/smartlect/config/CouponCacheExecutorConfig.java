package com.smartlect.config;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.jvm.ExecutorServiceMetrics;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicInteger;

@Configuration
public class CouponCacheExecutorConfig {

    public static final String CACHE_REBUILD_EXECUTOR = "CACHE_REBUILD_EXECUTOR";

    // ADR-0009：改用 ThreadPoolTaskExecutor 以获得 MDC 传播装饰器；语义保持——
    // 固定 10 线程 + 队列 500 + CallerRuns 回压 + daemon 命名线程。
    @Bean(name = CACHE_REBUILD_EXECUTOR)
    public Executor couponCacheRebuildExecutor(MeterRegistry meterRegistry) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(10);
        executor.setMaxPoolSize(10);
        executor.setQueueCapacity(500);
        executor.setThreadNamePrefix("coupon-cache-rebuild-");
        executor.setDaemon(true);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setTaskDecorator(new MdcTaskDecorator());
        executor.initialize();
        ExecutorServiceMetrics.monitor(meterRegistry, executor.getThreadPoolExecutor(), "smartlect.coupon.cache.rebuild");
        return executor;
    }
}
