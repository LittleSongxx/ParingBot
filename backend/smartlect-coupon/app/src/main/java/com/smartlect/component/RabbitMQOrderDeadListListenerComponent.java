package com.smartlect.component;

import com.smartlect.api.support.OrderFeignSupport;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.entity.po.UserCoupon;
import com.smartlect.biz.DiscountCouponService;
import com.smartlect.biz.UserCouponService;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 秒杀超时兜底（原死信队列语义，现为 15 分钟定时消息）：按「未建单/建单未落库/
 * 订单待支付/券已锁定但订单缺失」四种形态分别回滚 Redis 预占、回补库存或取消订单。
 */
@Slf4j
@Component
public class RabbitMQOrderDeadListListenerComponent implements SmartlectMessageListener<RushingCouponMessageDTO> {

    @Resource
    private DiscountCouponService discountCouponService;
    @Resource
    private UserCouponService userCouponService;
    @Resource
    private OrderFeignSupport orderFeignSupport;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_RUSH_TIMEOUT,
                "G_smartlect_rush_timeout");
    }

    @Override
    public Class<RushingCouponMessageDTO> payloadType() {
        return RushingCouponMessageDTO.class;
    }

    @Override
    public void onMessage(RushingCouponMessageDTO message, SmartlectMqMessage mqMessage) {
        String userCouponId = message.getUserCouponId();
        String userId = message.getUserId();
        String couponId = message.getCouponId();

        log.info("抢购超时兜底: userCouponId={}", userCouponId);

        UserCoupon userCoupon = userCouponService.getUserCouponByUserCouponId(userCouponId);
        OrderBriefVO orderInfo = StringTools.isEmpty(message.getOrderId())
                ? null
                : orderFeignSupport.getOrder(message.getOrderId());

        if (StringTools.isEmpty(message.getOrderId())) {
            if (userCoupon == null) {
                log.warn("抢购预占超时未建单，回补库存: couponId={}, userId={}", couponId, userId);
                discountCouponService.releaseRushCouponReserve(couponId, userId);
            }
            return;
        }

        if (userCoupon == null && orderInfo == null) {
            log.warn("建单未落库，仅回滚 Redis 预占: {}", userCouponId);
            discountCouponService.releaseRushRedisReserve(couponId, userId);
            return;
        }

        if (orderInfo != null
                && OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
            orderFeignSupport.cancelOrder(message.getOrderId(), null);
        } else if (userCoupon != null
                && UserCouponStatusEnum.CANT.getStatus().equals(userCoupon.getStatus())
                && orderInfo == null) {
            log.warn("用户券存在但订单缺失，仅回滚 Redis: {}", userCouponId);
            discountCouponService.releaseRushRedisReserve(couponId, userId);
        }
    }
}
