package com.smartlect.config;

import com.xxl.job.core.executor.impl.XxlJobSpringExecutor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * XXL-JOB 执行器配置：每个服务以自身 appname 注册到调度中心，
 * 任务由 admin 控制台统一定义与触发（替代 @Scheduled + Redis 自研锁）。
 */
@Slf4j
@Configuration
public class XxlJobConfig {

    @Value("${xxl.job.admin.addresses:}")
    private String adminAddresses;

    @Value("${xxl.job.accessToken:}")
    private String accessToken;

    @Value("${xxl.job.executor.appname:}")
    private String appname;

    @Value("${xxl.job.executor.port:9999}")
    private int port;

    /**
     * 执行器向调度中心自报的地址（可空）。空 = xxl-job 自动探测本机 IP——
     * 这在"调度中心跑在容器里、应用跑在宿主机"的本地形态下会报出局域网 IP，
     * 容器回不来，表现为**触发全部超时、兜底任务静默不执行**（2026-10-16 演练实测）。
     * 本地由 bootstrap 注入 host.docker.internal；生产留空或填真实内网 IP。
     */
    @Value("${xxl.job.executor.address:}")
    private String address;

    @Value("${xxl.job.executor.logpath:./logs/xxl-job}")
    private String logPath;

    @Value("${xxl.job.executor.logretentiondays:7}")
    private int logRetentionDays;

    @Bean
    public XxlJobSpringExecutor xxlJobExecutor() {
        XxlJobSpringExecutor executor = new XxlJobSpringExecutor();
        executor.setAdminAddresses(adminAddresses);
        executor.setAccessToken(accessToken);
        executor.setAppname(appname);
        executor.setPort(port);
        executor.setLogPath(logPath);
        executor.setLogRetentionDays(logRetentionDays);
        if (address != null && !address.isBlank()) {
            executor.setAddress(address);
        }
        log.info("XXL-JOB 执行器初始化 appname={} admin={} address={}", appname, adminAddresses,
                address == null || address.isBlank() ? "(auto)" : address);
        return executor;
    }
}
