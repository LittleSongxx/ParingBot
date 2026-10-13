package com.smartlect.api.support;

import com.smartlect.api.dubbo.OrderDubboService;
import com.smartlect.api.dto.CouponRushPayRequestDTO;
import com.smartlect.api.dto.CouponRushPrepareRequestDTO;
import com.smartlect.api.dto.OrderIdDTO;
import com.smartlect.api.dto.OrderStatsRangeDTO;
import com.smartlect.api.dto.UserIdDTO;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.vo.OrderDailyStatsVO;
import com.smartlect.api.vo.OrderRangeStatsVO;
import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;

@Component
public class OrderFeignSupport {

    @DubboReference
    private OrderDubboService orderFeignClient;
    @Resource
    private FeignResponseSupport feignResponseSupport;

    public OrderBriefVO getOrder(String orderId) {
        return feignResponseSupport.call(() -> orderFeignClient.getOrder(new OrderIdDTO(orderId)), "查询订单失败");
    }

    public void paySuccess(PayOrderNotifyDTO dto) {
        feignResponseSupport.run(() -> orderFeignClient.paySuccess(dto), "支付成功处理失败");
    }

    public CouponRushPrepareDTO prepareCouponRush(
            String userId, String couponId, String idempotencyKey) {
        return feignResponseSupport.call(
                () -> orderFeignClient.prepareCouponRush(
                        new CouponRushPrepareRequestDTO(userId, couponId), idempotencyKey),
                "秒杀预占失败");
    }

    public PayInfoDTO postCouponRushOrder(
            String userId, String couponId, String payMethod, String idempotencyKey) {
        return feignResponseSupport.call(
                () -> orderFeignClient.postCouponRushOrder(
                        new CouponRushPayRequestDTO(userId, couponId, payMethod), idempotencyKey),
                "秒杀下单支付失败");
    }

    public void syncPaidCouponRushUserCoupons(String userId) {
        feignResponseSupport.run(
                () -> orderFeignClient.syncPaidCouponRushUserCoupons(new UserIdDTO(userId)),
                "同步秒杀用户券失败");
    }

    public void cancelOrder(String orderId, String userId) {
        feignResponseSupport.run(
                () -> orderFeignClient.cancelOrder(new OrderIdDTO(orderId, userId)),
                "取消订单失败");
    }

    public OrderRangeStatsVO aggregateRange(String startTime, String endTime) {
        return feignResponseSupport.call(
                () -> orderFeignClient.aggregateRange(new OrderStatsRangeDTO(startTime, endTime)),
                "订单区间统计失败");
    }

    public List<OrderDailyStatsVO> aggregateDaily(String startTime, String endTime) {
        List<OrderDailyStatsVO> list = feignResponseSupport.call(
                () -> orderFeignClient.aggregateDaily(new OrderStatsRangeDTO(startTime, endTime)),
                "订单按日统计失败");
        return list == null ? Collections.emptyList() : list;
    }

    public void addAllWaitPayToDelayQueue() {
        feignResponseSupport.run(orderFeignClient::addAllWaitPayToDelayQueue, "待付款订单加入延时队列失败");
    }
}
