package com.smartlect.biz;

import java.util.List;
import java.util.Map;

import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.api.vo.OrderCountVO;
import com.smartlect.entity.vo.PaginationResultVO;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;

public interface OrderInfoService {

	List<OrderInfo> findListByParam(OrderInfoQuery param);

	/** 支付轮询对账：创建超过 delayMinutes 仍待付款的订单（按时间升序，限量）。 */
	List<OrderInfo> findWaitPaymentPollList(int delayMinutes, int limit);

	Integer findCountByParam(OrderInfoQuery param);

	PaginationResultVO<OrderInfo> findListByPage(OrderInfoQuery param);

	Integer add(OrderInfo bean);

	Integer addBatch(List<OrderInfo> listBean);

	Integer addOrUpdateBatch(List<OrderInfo> listBean);

	Integer updateByParam(OrderInfo bean,OrderInfoQuery param);

	Integer deleteByParam(OrderInfoQuery param);

	OrderInfo getOrderInfoByOrderId(String orderId);

	Integer updateOrderInfoByOrderId(OrderInfo bean,String orderId);

	Integer deleteOrderInfoByOrderId(String orderId);

    PayInfoDTO postOrder(
			@NotEmpty String userId,
			@Valid PostOrderDTO postOrderDTO,
			@NotEmpty String idempotencyKey);

    Map<String, Object> quoteOrder(String userId, PostOrderDTO request);

    PayInfoDTO createConfirmed(String userId, PostOrderDTO request, String quoteId,
                              Long confirmedAmountCents, String idempotencyKey);

	CouponRushPrepareDTO prepareCouponRush(
			@NotEmpty String userId,
			@NotEmpty String couponId,
			@NotEmpty String idempotencyKey);

	PayInfoDTO postCouponRushOrder(
			@NotEmpty String userId,
			@NotEmpty String couponId,
			@NotEmpty String payMethod,
			@NotEmpty String idempotencyKey);

	PayInfoDTO getPayInfo(@NotEmpty String userId,@NotEmpty String orderId);

	void cancelOrder(String userId, @NotEmpty String orderId,@NotEmpty OrderStatusEnum orderStatusEnum);

	void paySuccess(@NotEmpty PayOrderNotifyDTO payOrderNotifyDTO);

	void syncPaidCouponRushUserCoupons(@NotEmpty String userId);

	void refund(@NotEmpty OrderItem orderItem, String userId);

	List<OrderCountVO> getOrderCountInfo(String userId);

	boolean confirmOrderReceipt(String userId, String orderId);

	boolean cancelUnpaidOrderForPayTimeout(String orderId);

    PaginationResultVO<OrderInfo> findByProductNameFuzzy(PaginationResultVO<OrderInfo> resultVO, String productNameFuzzy);

	void addAllOrderToDelayQueue(List<OrderInfo> orderInfoList);

	void enrichCouponInfo(OrderInfo orderInfo);

	void enrichCouponInfo(List<OrderInfo> orderInfoList);
}
