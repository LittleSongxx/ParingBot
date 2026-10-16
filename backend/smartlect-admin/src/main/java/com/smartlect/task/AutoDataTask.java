package com.smartlect.task;

import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.entity.enums.DateTimePatternEnum;
import com.smartlect.biz.StatisticsInfoService;
import com.smartlect.utils.DateUtil;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import com.xxl.job.core.handler.annotation.XxlJob;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

@Component
@ConditionalOnProperty(name = "app.auto-data-task.enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class AutoDataTask {

    @Resource
    private StatisticsInfoService statisticsInfoService;

    @Resource
    private RedisComponent redisComponent;

    @Value("${spring.application.name:unknown}")
    private String applicationName;

    // 每天的凌晨一点自动统计昨天的数据
    @XxlJob("autoDataTask")
    public void autoCountYesterdayData() {
        countYesterdayData("定时");
    }

    /**
     * 启动补齐：机器在 01:00 停机时会漏掉当日日结，靠启动时补一次。
     *
     * <p>原先这是 {@code @PostConstruct}，两个问题在多副本下都会放大：装配期跑日结
     * 意味着聚合失败会直接让实例起不来（RPC 打不通 order 就整台起不来），
     * 而滚动重启又会让每个副本各补一次。改为就绪事件 + 共用同一把锁。
     */
    @EventListener(ApplicationReadyEvent.class)
    public void catchUpOnStartup() {
        countYesterdayData("启动补齐");
    }

    private void countYesterdayData(String trigger) {
        // 锁键拼 applicationName：同服务的副本互斥，键值 TTL 覆盖单次最长执行时间。
        // 日任务间隔是 24 小时，不能照搬"TTL 略小于间隔"的做法，否则锁跨天残留。
        String lockKey = Constants.REDIS_KEY_ADMIN_AUTO_DATA_LOCK + applicationName;
        if (!redisComponent.setIfAbsent(lockKey, "1", 10, TimeUnit.MINUTES)) {
            log.info("统计日结已由其他实例执行，跳过本次（{}）", trigger);
            return;
        }
        try {
            // 获取系统当前时间yyyyMMddHHss格式
            String start = DateUtil.getTimeOnParttern(1, DateTimePatternEnum.YYYY_MM_DD.getPattern()) + " 01:00:00";
            String end = DateUtil.getTimeOnParttern(0, DateTimePatternEnum.YYYY_MM_DD_HH_MM_SS.getPattern());
            statisticsInfoService.statistics(start, end);
            log.info("同步统计数据完成（{}）", trigger);
        } catch (Exception e) {
            // 补齐失败不能影响实例就绪：下一次定时或下一轮启动会重试，日结本身是 upsert 幂等的
            log.error("同步统计数据失败（{}）", trigger, e);
        }
    }
}
