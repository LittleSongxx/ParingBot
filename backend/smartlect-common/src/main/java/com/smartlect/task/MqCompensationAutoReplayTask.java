package com.smartlect.task;

import com.smartlect.component.RedisComponent;
import com.smartlect.metrics.SmartlectMetrics;
import com.smartlect.constants.Constants;
import com.smartlect.service.MqCompensationLogService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import com.xxl.job.core.handler.annotation.XxlJob;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

@Component
@Slf4j
@ConditionalOnProperty(name = "mq.compensation.auto-replay-enabled", havingValue = "true")
public class MqCompensationAutoReplayTask {

    @Resource
    private MqCompensationLogService mqCompensationLogService;
    @Resource
    private SmartlectMetrics metrics;
    @Resource
    private RedisComponent redisComponent;

    @Value("${mq.compensation.auto-replay-batch-size:10}")
    private int batchSize;

    @Value("${mq.compensation.auto-replay-max-retries:5}")
    private int maxRetries;

    @Value("${spring.application.name:unknown}")
    private String applicationName;

    @XxlJob("mqCompensationReplay")
    public void autoReplay() {
        String lockKey = Constants.REDIS_KEY_MQ_COMPENSATE_AUTO_REPLAY_LOCK
                + ":" + applicationName;
        if (!redisComponent.setIfAbsent(
                lockKey,
                "1",
                55,
                TimeUnit.SECONDS)) {
            return;
        }
        try {
            int count = mqCompensationLogService.autoReplayPendingSendFailures(batchSize, maxRetries);
            if (count > 0) {
                metrics.compensationReplayed(count);
                log.info("MQ 发送补偿自动重放完成，成功 {} 条", count);
            }
        } catch (Exception e) {
            log.error("MQ 发送补偿自动重放任务异常", e);
        }
    }
}
