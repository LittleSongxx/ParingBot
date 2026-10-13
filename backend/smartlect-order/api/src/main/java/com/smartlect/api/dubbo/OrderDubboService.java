package com.smartlect.api.dubbo;

import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.dto.CouponRushPayRequestDTO;
import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.CouponRushPrepareRequestDTO;
import com.smartlect.api.dto.OrderIdDTO;
import com.smartlect.api.dto.OrderStatsRangeDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.dto.UserIdDTO;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.vo.OrderDailyStatsVO;
import com.smartlect.api.vo.OrderRangeStatsVO;
import java.util.List;


/**
 * order 域内部 Dubbo 契约（取代原 FeignClient，方法签名一致；
 * HTTP /internal 端点保留给 assistant 与运维，双通道共用同一 Service 层）。
 */
public interface OrderDubboService {

    ResponseVO<OrderBriefVO> getOrder(OrderIdDTO dto);

    ResponseVO<Boolean> cancelUnpaidForPayTimeout(OrderIdDTO dto);

    ResponseVO<Boolean> confirmReceipt(OrderIdDTO dto);

    ResponseVO<Void> paySuccess(PayOrderNotifyDTO dto);

    ResponseVO<CouponRushPrepareDTO> prepareCouponRush(CouponRushPrepareRequestDTO dto, String idempotencyKey);

    ResponseVO<PayInfoDTO> postCouponRushOrder(CouponRushPayRequestDTO dto, String idempotencyKey);

    ResponseVO<Void> syncPaidCouponRushUserCoupons(UserIdDTO dto);

    ResponseVO<Void> cancelOrder(OrderIdDTO dto);

    ResponseVO<OrderRangeStatsVO> aggregateRange(OrderStatsRangeDTO dto);

    ResponseVO<java.util.List<OrderDailyStatsVO>> aggregateDaily(OrderStatsRangeDTO dto);

    ResponseVO<Void> addAllWaitPayToDelayQueue();

}
