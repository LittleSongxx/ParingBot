package com.smartlect.task;

import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import com.xxl.job.core.handler.annotation.XxlJob;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * 支付轮询对账（ADR-0004）：兜底支付成功 MQ 事件丢失/进程崩溃后的状态收敛。
 * 旧实现依赖 isPayTradeInitiated 的 Redis 标记过滤，但该标记从无生产写入方，
 * 轮询永远空转（死路径）；现改为按"创建超过 N 分钟仍待付款"直接对账查渠道。
 */
@Component
@Slf4j
public class PayOrderTask {

    @Resource
    private AppConfig appConfig;

    @Resource
    private OrderInfoService orderInfoService;

    @Resource
    private PayRpcSupport payRpcSupport;

    @Resource
    private RedisComponent redisComponent;

    @Value("${spring.application.name:unknown}")
    private String applicationName;

    /** 只对账创建超过该秒数的待付款单：正在正常支付的用户不查渠道。 */
    @Value("${smartlect.pay.poll-min-age-seconds:180}")
    private int pollMinAgeSeconds;

    @Value("${smartlect.pay.poll-batch-size:200}")
    private int pollBatchSize;

    @XxlJob("payOrderPoll")
    public void pollPayOrders() {
        if (!appConfig.getAutoCheckpay()) {
            return;
        }
        // 轮询要打支付渠道查询接口：多副本各自轮一遍等于外部调用量翻 N 倍。
        // 用一把 key 带 applicationName 的短锁（TTL 略短于 5s 间隔）把轮询收敛到单副本；
        // 落库路径本身有单号粒度的 Redisson 锁 + 条件更新，漏掉一轮轮询不影响正确性。
        String lockKey = Constants.REDIS_KEY_ORDER_PAY_POLL_LOCK + applicationName;
        if (!redisComponent.setIfAbsent(lockKey, "1", 4, TimeUnit.SECONDS)) {
            return;
        }
        try {
            int delayMinutes = Math.max(1, pollMinAgeSeconds / 60);
            List<OrderInfo> orderInfoList =
                    orderInfoService.findWaitPaymentPollList(delayMinutes, pollBatchSize);
            for (OrderInfo orderInfo : orderInfoList) {
                reconcileOne(orderInfo);
            }
        } catch (Exception e) {
            log.error("支付轮询对账批次异常", e);
        }
    }

    private void reconcileOne(OrderInfo orderInfo) {
        String payOrderId = orderInfo.getPayOrderId();
        if (StringTools.isEmpty(payOrderId)) {
            // 无支付单号的待付款单由超时关单延时消息收敛，这里不处理。
            return;
        }
        PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
        if (payChannelEnum == null) {
            return;
        }
        try {
            // 渠道侧无结果（PENDING / 意图不存在）返回 null，交由超时关单收敛；
            PayOrderNotifyDTO payOrderNotifyDTO =
                    payRpcSupport.queryOrder(payOrderId, payChannelEnum.getPayScene());
            if (payOrderNotifyDTO == null) {
                return;
            }
            orderInfoService.paySuccess(payOrderNotifyDTO);
        } catch (Exception e) {
            // 单笔对账失败不阻断整批：失败单留在待付款集合里下一轮重试。
            log.warn("支付轮询对账单笔失败, payOrderId={}", payOrderId, e);
        }
    }
}
