package com.smartlect.controller.internal;

import com.smartlect.api.dto.CouponRushPayRequestDTO;
import com.smartlect.api.dto.CouponRushPrepareRequestDTO;
import com.smartlect.api.dto.OrderIdDTO;
import com.smartlect.api.dto.OrderStatsRangeDTO;
import com.smartlect.api.dto.UserIdDTO;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.vo.OrderDailyStatsVO;
import com.smartlect.api.vo.OrderRangeStatsVO;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderInternalService;
import com.smartlect.controller.ABaseController;
import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/internal/order")
public class OrderInternalController extends ABaseController {

    @Resource
    private OrderInternalService orderInternalService;

    @Resource
    private OrderInfoService orderInfoService;

    @PostMapping("/get")
    public ResponseVO<OrderBriefVO> getOrder(@RequestBody OrderIdDTO dto) {
        return getSuccessResponseVO(orderInternalService.getOrder(dto));
    }

    @PostMapping("/cancelUnpaidForPayTimeout")
    public ResponseVO<Boolean> cancelUnpaidForPayTimeout(@RequestBody OrderIdDTO dto) {
        return getSuccessResponseVO(orderInternalService.cancelUnpaidForPayTimeout(dto));
    }

    @PostMapping("/confirmReceipt")
    public ResponseVO<Boolean> confirmReceipt(@RequestBody OrderIdDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto == null ? null : dto.getUserId());
        return getSuccessResponseVO(orderInternalService.confirmReceipt(dto));
    }

    @PostMapping("/paySuccess")
    public ResponseVO<Void> paySuccess(@RequestBody PayOrderNotifyDTO dto) {
        orderInternalService.paySuccess(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/prepareCouponRush")
    public ResponseVO<CouponRushPrepareDTO> prepareCouponRush(
            @RequestBody CouponRushPrepareRequestDTO dto,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey) {
        return getSuccessResponseVO(orderInternalService.prepareCouponRush(dto, idempotencyKey));
    }

    @PostMapping("/postCouponRushOrder")
    public ResponseVO<PayInfoDTO> postCouponRushOrder(
            @RequestBody CouponRushPayRequestDTO dto,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey) {
        return getSuccessResponseVO(orderInternalService.postCouponRushOrder(dto, idempotencyKey));
    }

    @PostMapping("/syncPaidCouponRushUserCoupons")
    public ResponseVO<Void> syncPaidCouponRushUserCoupons(@RequestBody UserIdDTO dto) {
        orderInternalService.syncPaidCouponRushUserCoupons(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/cancelOrder")
    public ResponseVO<Void> cancelOrder(@RequestBody OrderIdDTO dto) {
        // Coupon timeout cancel goes through the RPC facade with no delegated user.
        // After /internal is off the public gateway, token on the order port is the gate.
        orderInternalService.cancelOrder(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/stats/range")
    public ResponseVO<OrderRangeStatsVO> aggregateRange(@RequestBody OrderStatsRangeDTO dto) {
        return getSuccessResponseVO(orderInternalService.aggregateRange(dto));
    }

    @PostMapping("/stats/daily")
    public ResponseVO<List<OrderDailyStatsVO>> aggregateDaily(@RequestBody OrderStatsRangeDTO dto) {
        return getSuccessResponseVO(orderInternalService.aggregateDaily(dto));
    }

    @PostMapping("/tool/addAllWaitPayToDelayQueue")
    public ResponseVO<Void> addAllWaitPayToDelayQueue() {
        OrderInfoQuery orderInfoQuery = new OrderInfoQuery();
        orderInfoQuery.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
        List<OrderInfo> orderInfoList = orderInfoService.findListByParam(orderInfoQuery);
        orderInfoService.addAllOrderToDelayQueue(orderInfoList);
        return getSuccessResponseVO(null);
    }
}
