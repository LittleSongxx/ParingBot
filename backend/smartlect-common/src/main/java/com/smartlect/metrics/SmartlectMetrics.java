package com.smartlect.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

/**
 * 业务指标单一出口。
 *
 * <p>命名约定：{@code smartlect_<域>_<事件>_total}，标签只放<b>有限基数</b>的维度
 * （服务名由 {@code management.metrics.tags.application} 统一附加）。
 * 指标含义与抓取方式见 README「指标与观测」一节——这里是名字的唯一事实源，
 * 新增指标请走本类，不要在业务代码里散落 {@code Counter.builder(...)}。</p>
 */
@Component
public class SmartlectMetrics {

    public static final String ORDER_CREATED = "smartlect_order_created_total";
    public static final String IDEMPOTENT_REPLAY = "smartlect_idempotent_replay_total";
    public static final String IDEMPOTENT_CONFLICT = "smartlect_idempotent_conflict_total";
    public static final String STOCK_INSUFFICIENT = "smartlect_stock_insufficient_total";
    public static final String OUTBOX_DISPATCH = "smartlect_outbox_dispatch_total";
    public static final String COMPENSATION_REPLAYED = "smartlect_mq_compensation_replayed_total";
    public static final String PRODUCT_CACHE = "smartlect_product_cache_total";
    public static final String SLOW_SQL = "smartlect_sql_slow_total";

    private final MeterRegistry registry;

    public SmartlectMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    /** 下单成功：Phase 3 短事务提交后按子单数累加。 */
    public void orderCreated(int orders) {
        Counter.builder(ORDER_CREATED).register(registry).increment(orders);
    }

    /** 幂等重放命中：同一幂等键的重复请求直接返回既有结果（正常路径，不是异常）。 */
    public void idempotentReplay(String command) {
        Counter.builder(IDEMPOTENT_REPLAY).tag("command", command).register(registry).increment();
    }

    /** 幂等冲突：处理中 / 陈旧待核对 / 需人工 / 已失败 / 指纹不一致等 409 分支。 */
    public void idempotentConflict(String command, String reason) {
        Counter.builder(IDEMPOTENT_CONFLICT).tag("command", command).tag("reason", reason)
                .register(registry).increment();
    }

    /** 库存不足：条件更新影响 0 行（防超卖的正常拒绝，不是系统故障）。 */
    public void stockInsufficient() {
        Counter.builder(STOCK_INSUFFICIENT).register(registry).increment();
    }

    /** Outbox 投递结果：sent / failed / parked（撞 broker 时间轮上限，驻留待重投）。 */
    public void outboxDispatch(String result) {
        Counter.builder(OUTBOX_DISPATCH).tag("result", result).register(registry).increment();
    }

    /** 补偿日志自动重放成功条数（重放失败不计入，失败留在日志表下一轮再试）。 */
    public void compensationReplayed(int count) {
        if (count > 0) {
            Counter.builder(COMPENSATION_REPLAYED).register(registry).increment(count);
        }
    }

    /** 慢 SQL：按 mapperId 计数（阈值见 smartlect.sql.slow-threshold-ms，默认 200ms）。 */
    public void slowSql(String mapperId) {
        Counter.builder(SLOW_SQL).tag("mapper", mapperId).register(registry).increment();
    }

    /** 商品详情缓存：layer = l1 / l2 / db，result = hit / miss / error / load。 */
    public void productCache(String layer, String result) {
        Counter.builder(PRODUCT_CACHE).tag("layer", layer).tag("result", result)
                .register(registry).increment();
    }
}
