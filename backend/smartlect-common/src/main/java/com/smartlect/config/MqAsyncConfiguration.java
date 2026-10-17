package com.smartlect.config;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.binder.jvm.ExecutorServiceMetrics;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * Outbox afterCommit 异步投递线程池（ADR-0009 调整）：
 * 旧参数 queue=2000 压制 max=16（Java 线程池先填满队列再扩容，max 基本永不生效，
 * 高峰实际只有 4 个投递线程）；队列缩到 200 让 max 生效，参数全部可配；
 * 新增 MDC 传播装饰器与停机 drain（等待队列内任务完成，配合 outbox 兜底扫描双保险）。
 */
@Configuration
public class MqAsyncConfiguration {

    @Bean(name = "mqAsyncExecutor")
    public Executor mqAsyncExecutor(
            MeterRegistry meterRegistry,
            @Value("${smartlect.mq.async.core-pool-size:4}") int corePoolSize,
            @Value("${smartlect.mq.async.max-pool-size:16}") int maxPoolSize,
            @Value("${smartlect.mq.async.queue-capacity:200}") int queueCapacity) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(queueCapacity);
        executor.setThreadNamePrefix("mq-async-");
        executor.setTaskDecorator(new MdcTaskDecorator());
        // 停机时等待队列任务完成（最多 30s）：落库的 outbox 行由兜底任务重投，双保险
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        // 队列深度 / 活跃线程 / 拒绝次数必须可观测：参数调优与"池是否被打满"都靠它
        ExecutorServiceMetrics.monitor(meterRegistry, executor.getThreadPoolExecutor(), "smartlect.mq.async");
        return executor;
    }
}
