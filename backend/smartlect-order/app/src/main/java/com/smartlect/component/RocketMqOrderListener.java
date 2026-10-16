package com.smartlect.component;

import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * 清退旧秒杀队列残留：订单或用户券任一存在即视为已结算，否则跳过不重建订单。
 */
@Slf4j
@Component
public class RocketMqOrderListener implements SmartlectMessageListener<RushingCouponMessageDTO> {

    @Resource
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Resource
    private CouponRpcSupport couponRpcSupport;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_RUSH, RocketMqTopics.TAG_RUSH_ORDER,
                "G_smartlect_rush_order");
    }

    @Override
    public Class<RushingCouponMessageDTO> payloadType() {
        return RushingCouponMessageDTO.class;
    }

    @Override
    public void onMessage(RushingCouponMessageDTO message, SmartlectMqMessage mqMessage) {
        String userCouponId = message == null ? null : message.getUserCouponId();
        if (message == null || message.getOrderId() == null || userCouponId == null) {
            throw new IllegalArgumentException("leftover rush queue message incomplete");
        }
        if (orderInfoMapper.selectByOrderId(message.getOrderId()) != null
                || couponRpcSupport.getUserCoupon(userCouponId) != null) {
            return;
        }
        log.warn("drain leftover rush queue, skip order create userCouponId={}", userCouponId);
    }
}
