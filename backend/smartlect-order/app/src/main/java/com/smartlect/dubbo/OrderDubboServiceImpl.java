package com.smartlect.dubbo;

import com.smartlect.api.dubbo.OrderDubboService;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import com.smartlect.controller.internal.OrderInternalController;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * order 域 Dubbo provider：直接委托 internal controller（与 HTTP 通道共用
 * 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class OrderDubboServiceImpl implements OrderDubboService {

    @Resource
    private OrderInternalController orderInternalController;

    @Override
    public ResponseVO<OrderBriefVO> getOrder(OrderIdDTO dto) {
        return orderInternalController.getOrder(dto);
    }

    @Override
    public ResponseVO<Boolean> cancelUnpaidForPayTimeout(OrderIdDTO dto) {
        return orderInternalController.cancelUnpaidForPayTimeout(dto);
    }

    @Override
    public ResponseVO<Boolean> confirmReceipt(OrderIdDTO dto) {
        return orderInternalController.confirmReceipt(dto);
    }

    @Override
    public ResponseVO<Void> paySuccess(PayOrderNotifyDTO dto) {
        return orderInternalController.paySuccess(dto);
    }

    @Override
    public ResponseVO<CouponRushPrepareDTO> prepareCouponRush(CouponRushPrepareRequestDTO dto, String idempotencyKey) {
        return orderInternalController.prepareCouponRush(dto, idempotencyKey);
    }

    @Override
    public ResponseVO<PayInfoDTO> postCouponRushOrder(CouponRushPayRequestDTO dto, String idempotencyKey) {
        return orderInternalController.postCouponRushOrder(dto, idempotencyKey);
    }

    @Override
    public ResponseVO<Void> syncPaidCouponRushUserCoupons(UserIdDTO dto) {
        return orderInternalController.syncPaidCouponRushUserCoupons(dto);
    }

    @Override
    public ResponseVO<Void> cancelOrder(OrderIdDTO dto) {
        return orderInternalController.cancelOrder(dto);
    }

    @Override
    public ResponseVO<OrderRangeStatsVO> aggregateRange(OrderStatsRangeDTO dto) {
        return orderInternalController.aggregateRange(dto);
    }

    @Override
    public ResponseVO<java.util.List<OrderDailyStatsVO>> aggregateDaily(OrderStatsRangeDTO dto) {
        return orderInternalController.aggregateDaily(dto);
    }

    @Override
    public ResponseVO<Void> addAllWaitPayToDelayQueue() {
        return orderInternalController.addAllWaitPayToDelayQueue();
    }

}
