package com.smartlect.biz.impl;

import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.dto.PostOrderDTO;
import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.support.ProductRpcSupport;
import com.smartlect.api.support.UserRpcSupport;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.OrderCountVO;
import com.smartlect.api.vo.UserBriefVO;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.RefundSagaService;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.exception.PayOrderLifecycleBusyException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.OrderPayAmountUtil;
import com.smartlect.utils.PageUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 订单门面（ADR-0002）：对外保持 {@link OrderInfoService} 契约不变，交易写路径委托给
 * 三个领域服务——{@link OrderCreationService}（下单/报价）、{@link OrderPaymentService}
 * （支付回调）、{@link OrderCancellationService}（取消/关单）；本类保留查询/富化/统计与
 * 确认收货。曾为 1509 行的上帝类，拆分后各职责单一、可独立演进。
 */
@Service("orderInfoService")
@Slf4j
public class OrderInfoServiceImpl implements OrderInfoService {

	@Resource
	private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
	@Resource
	private OrderStateMachine orderStateMachine;
	@Resource
	private ProductRpcSupport productRpcSupport;
	@Resource
	private UserRpcSupport userRpcSupport;
	@Resource
	private CouponRpcSupport couponRpcSupport;
	@Resource
	private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
	@Resource
	private OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
	@Resource
	private RefundSagaService refundSagaService;
	@Resource
	private TransactionalMqSender transactionalMqSender;
	@Resource
	private CouponRushOrderService couponRushOrderService;

	// 领域服务（拆分本体）
	@Resource
	private OrderCreationService orderCreationService;
	@Resource
	private OrderPaymentService orderPaymentService;
	@Resource
	private OrderCancellationService orderCancellationService;

	// getPayInfo 需要拉取支付表单（远程）
	@Resource
	private com.smartlect.api.support.PayRpcSupport payRpcSupport;

	@Override
	public List<OrderInfo> findListByParam(OrderInfoQuery param) {
		List<OrderInfo> list = this.orderInfoMapper.selectList(param);
		if (list != null && !list.isEmpty()) {
			if (Boolean.TRUE.equals(param.isQueryItems())) {
				enrichCouponInfo(list);
			}
			if (Boolean.TRUE.equals(param.getQueryUser())) {
				enrichUserBrief(list);
			}
		}
		return list;
	}

	@Override
	public List<OrderInfo> findWaitPaymentPollList(int delayMinutes, int limit) {
		return orderInfoMapper.selectWaitPaymentBefore(delayMinutes, limit);
	}

	@Override
	public Integer findCountByParam(OrderInfoQuery param) {
		return this.orderInfoMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<OrderInfo> findListByPage(OrderInfoQuery param) {
		return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> this.findListByParam(param));
	}

	@Override
	public Integer add(OrderInfo bean) {
		return this.orderInfoMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<OrderInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderInfoMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<OrderInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderInfoMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(OrderInfo bean, OrderInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderInfoMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(OrderInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderInfoMapper.deleteByParam(param);
	}

	@Override
	public OrderInfo getOrderInfoByOrderId(String orderId) {
		return this.orderInfoMapper.selectByOrderId(orderId);
	}

	@Override
	public Integer updateOrderInfoByOrderId(OrderInfo bean, String orderId) {
		return this.orderInfoMapper.updateByOrderId(bean, orderId);
	}

	@Override
	public Integer deleteOrderInfoByOrderId(String orderId) {
		return this.orderInfoMapper.deleteByOrderId(orderId);
	}

	@Override
	public PayInfoDTO postOrder(String userId, PostOrderDTO postOrderDTO, String idempotencyKey) {
		return orderCreationService.postOrder(userId, postOrderDTO, idempotencyKey);
	}

	@Override
	public Map<String, Object> quoteOrder(String userId, PostOrderDTO request) {
		return orderCreationService.quoteOrder(userId, request);
	}

	@Override
	public PayInfoDTO createConfirmed(String userId, PostOrderDTO request, String quoteId,
			Long confirmedAmountCents, String idempotencyKey) {
		return orderCreationService.createConfirmed(userId, request, quoteId, confirmedAmountCents, idempotencyKey);
	}

	// 获取支付信息
	@Override
	public PayInfoDTO getPayInfo(String userId, String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			OrderInfoQuery payQuery = new OrderInfoQuery();
			payQuery.setPayOrderId(orderId);
			payQuery.setUserId(userId);
			List<OrderInfo> payOrders = orderInfoMapper.selectList(payQuery);
			if (!payOrders.isEmpty()) {
				orderInfo = payOrders.get(0);
			}
		}
		if (orderInfo == null || !orderInfo.getUserId().equals(userId)) {
			throw new BusinessException("订单不存在");
		}
		// 判断当前订单状态是否为待支付
		if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
			if (OrderStatusEnum.CLOSED.getStatus().equals(orderInfo.getOrderStatus())
					|| OrderStatusEnum.CANCELLED.getStatus().equals(orderInfo.getOrderStatus())) {
				throw new BusinessException("订单已关闭，请重新抢购");
			}
			throw new BusinessException("当前订单已支付");
		}
		PayChannelEnum payChannelEnum = orderPaymentService.resolveWaitPayChannel(orderInfo);
		String subject = orderInfo.getSubject();
		// 查询同一payOrderId下的所有订单,计算总金额
		List<OrderInfo> payOrderList = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, orderInfo.getPayOrderId());
		BigDecimal amount = payOrderList.stream()
				.map(OrderInfo::getAmount)
				.reduce(BigDecimal.ZERO, BigDecimal::add);  // 累加所有订单金额
		amount = OrderPayAmountUtil.normalizeChannelPayAmount(amount);
		String payOrderId = orderInfo.getPayOrderId();

		PayInfoDTO payInfoDTO = payRpcSupport.getPayUrl(payChannelEnum.getPayScene(), payOrderId, subject, amount, userId);
		if (payChannelEnum != PayChannelEnum.MOCK) {
			orderCancellationService.cancelOrder4Channel(orderInfo);
		}

		//更新支付订单ID
		OrderInfo updateOrderInfo = new OrderInfo();
		updateOrderInfo.setPayOrderId(payOrderId);
		orderInfoMapper.updateByOrderId(updateOrderInfo, orderInfo.getOrderId());
		return payInfoDTO;
	}

	// 取消订单：委托取消领域服务（短事务 CAS + 事务外幂等远程收敛）
	@Override
	public void cancelOrder(String userId, String orderId, OrderStatusEnum orderStatusEnum) {
		orderCancellationService.cancelOrder(userId, orderId, orderStatusEnum);
	}

	// 支付成功信息：委托支付领域服务（短事务 CAS + 事务外幂等远程写）
	@Override
	public void paySuccess(PayOrderNotifyDTO payOrderNotifyDTO) {
		orderPaymentService.paySuccess(payOrderNotifyDTO);
	}

	// 秒杀下单的校验/预占/建单/支付在 CouponRushOrderServiceImpl，这里只保留接口契约的委托。
	@Override
	public CouponRushPrepareDTO prepareCouponRush(
			String userId, String couponId, String idempotencyKey) {
		return couponRushOrderService.prepareCouponRush(userId, couponId, idempotencyKey);
	}

	@Override
	public PayInfoDTO postCouponRushOrder(
			String userId, String couponId, String payMethod, String idempotencyKey) {
		return couponRushOrderService.postCouponRushOrder(userId, couponId, payMethod, idempotencyKey);
	}

	@Override
	public void syncPaidCouponRushUserCoupons(String userId) {
		couponRushOrderService.syncPaidCouponRushUserCoupons(userId);
	}

	@Override
	public void refund(OrderItem orderItem, String userId) {
		refundSagaService.requestRefund(orderItem, userId);
	}

	@Override
	public List<OrderCountVO> getOrderCountInfo(String userId) {
		OrderInfoQuery query = new OrderInfoQuery();
		query.setUserId(userId);
		List<OrderInfo> orderInfoList = orderInfoMapper.selectList(query);
		OrderCountVO orderCountVO1 = new OrderCountVO();
		OrderCountVO orderCountVO2 = new OrderCountVO();
		OrderCountVO orderCountVO3 = new OrderCountVO();
		OrderCountVO orderCountVO5 = new OrderCountVO();
		List<OrderCountVO> orderCountVOList = new ArrayList<>();
		Integer waitPayCount = 0;
		Integer waitShipCount = 0;
		Integer waitReceiveCount = 0;
		Set<String> completedPayOrderIds = new HashSet<>();
		for (OrderInfo orderInfo : orderInfoList) {
			// 已删除的不统计
			if (OrderStatusEnum.DELETE.getStatus().equals(orderInfo.getOrderStatus())){
				continue;
			}
			if (OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())){
				waitPayCount++;
			} else if (OrderStatusEnum.PAID.getStatus().equals(orderInfo.getOrderStatus())) {
				waitShipCount++;
			}else if(OrderStatusEnum.SHIPPED.getStatus().equals(orderInfo.getOrderStatus())){
				waitReceiveCount++;
			}
			if (OrderStatusEnum.COMPLETED.getStatus().equals(orderInfo.getOrderStatus())){
				completedPayOrderIds.add(orderInfo.getOrderId());
			}
		}
		Integer completedCount = completedPayOrderIds.size();
		orderCountVO1.setCode("pendingPayment");
		orderCountVO1.setCount(waitPayCount);
		orderCountVOList.add(orderCountVO1);
		orderCountVO2.setCode("pendingShipment");
		orderCountVO2.setCount(waitShipCount);
		orderCountVOList.add(orderCountVO2);
		orderCountVO3.setCode("pendingReceipt");
		orderCountVO3.setCount(waitReceiveCount);
		orderCountVOList.add(orderCountVO3);
		orderCountVO5.setCode("completed");
		orderCountVO5.setCount(completedCount);
		orderCountVOList.add(orderCountVO5);
		return orderCountVOList;
	}

	@Override
	public PaginationResultVO<OrderInfo> findByProductNameFuzzy(PaginationResultVO<OrderInfo> resultVO, String productNameFuzzy) {
		List<OrderInfo> orderInfoList = resultVO.getList();
		List<OrderInfo> newList = new ArrayList<>();
		int flag;
		for (OrderInfo orderInfo : orderInfoList) {
			flag = 0;
			for (OrderItem orderItem : orderInfo.getOrderItemList()){
				if (!orderItem.getProductName().contains(productNameFuzzy)) {
					continue;
				}
				if (flag == 1) {
					continue;
				}
				flag = 1;
				newList.add(orderInfo);
			}
		}
		resultVO.setList(newList);
		return resultVO;
	}

	@Override
	public void addAllOrderToDelayQueue(List<OrderInfo> orderInfoList) {
		// 将orderId逐个加入到延迟队列（事务提交后发送）
		for (OrderInfo orderInfo : orderInfoList) {
			PayOrderMessageDTO dto = new PayOrderMessageDTO();
			dto.setOrderId(orderInfo.getOrderId());
			transactionalMqSender.sendAfterCommit(
					RocketMqTopics.TOPIC_PAY,
					RocketMqTopics.TAG_PAY_TIMEOUT_CLOSE,
					dto,
					MqIdempotencyKeys.payTimeout(orderInfo.getOrderId()),
					MessageReliabilityLevelEnum.STANDARD,
					System.currentTimeMillis() + RocketMqTopics.PAY_TIMEOUT.toMillis());
		}
	}

	@Override
	public void enrichCouponInfo(OrderInfo orderInfo) {
		if (orderInfo == null) {
			return;
		}
		if (OrderFacts.isCouponRushOrder(orderInfo)) {
			BigDecimal amt = orderInfo.getAmount() == null ? BigDecimal.ZERO : orderInfo.getAmount();
			orderInfo.setOriginalAmount(amt);
			orderInfo.setCouponDiscountAmount(BigDecimal.ZERO);
			return;
		}
		BigDecimal original = sumItemAmount(orderInfo.getOrderItemList(), true);
		BigDecimal payAmount = orderInfo.getAmount() == null ? BigDecimal.ZERO : orderInfo.getAmount();
		orderInfo.setOriginalAmount(original);
		BigDecimal discount = original.subtract(payAmount);
		if (discount.compareTo(BigDecimal.ZERO) < 0) {
			discount = BigDecimal.ZERO;
		}
		discount = discount.setScale(2, RoundingMode.HALF_UP);
		orderInfo.setCouponDiscountAmount(discount);
		if (discount.compareTo(BigDecimal.ZERO) <= 0) {
			return;
		}
		OrderCouponRel rel = findCouponRelForOrder(orderInfo);
		if (rel == null || StringTools.isEmpty(rel.getCouponId())) {
			return;
		}
		CouponBriefVO coupon = couponRpcSupport.getCouponBrief(rel.getCouponId());
		if (coupon != null) {
			orderInfo.setCouponName(coupon.getCouponName());
			orderInfo.setCouponType(coupon.getCouponType());
		}
	}

	@Override
	public void enrichCouponInfo(List<OrderInfo> orderInfoList) {
		if (orderInfoList == null || orderInfoList.isEmpty()) {
			return;
		}
		for (OrderInfo orderInfo : orderInfoList) {
			enrichCouponInfo(orderInfo);
		}
	}

	private void enrichUserBrief(List<OrderInfo> list) {
		List<String> userIds = list.stream()
				.map(OrderInfo::getUserId)
				.filter(id -> !StringTools.isEmpty(id))
				.distinct()
				.collect(Collectors.toList());
		Map<String, UserBriefVO> map = userRpcSupport.mapBriefByUserIds(userIds);
		for (OrderInfo order : list) {
			UserBriefVO brief = map.get(order.getUserId());
			if (brief != null) {
				order.setNickName(brief.getNickName());
				order.setAvatar(brief.getAvatar());
			}
		}
	}

	private BigDecimal sumItemAmount(List<OrderItem> items, boolean normalOnly) {
		BigDecimal total = BigDecimal.ZERO;
		if (items == null) {
			return total;
		}
		for (OrderItem item : items) {
			if (normalOnly && !OrderItemStatusEnum.NORMAL.getStatus().equals(item.getOrderItemStatus())) {
				continue;
			}
			BigDecimal itemAmount = item.getItemAmount() == null ? BigDecimal.ZERO : item.getItemAmount();
			total = total.add(itemAmount);
		}
		return total.setScale(2, RoundingMode.HALF_UP);
	}

	private OrderCouponRel findCouponRelForOrder(OrderInfo orderInfo) {
		OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
		relQuery.setOrderId(orderInfo.getOrderId());
		List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
		if (rels != null && !rels.isEmpty()) {
			return rels.get(0);
		}
		if (StringTools.isEmpty(orderInfo.getPayOrderId())) {
			return null;
		}
		List<OrderInfo> siblings = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, orderInfo.getPayOrderId());
		if (siblings == null) {
			return null;
		}
		for (OrderInfo sibling : siblings) {
			if (sibling == null || orderInfo.getOrderId().equals(sibling.getOrderId())) {
				continue;
			}
			relQuery.setOrderId(sibling.getOrderId());
			rels = orderCouponRelMapper.selectList(relQuery);
			if (rels != null && !rels.isEmpty()) {
				return rels.get(0);
			}
		}
		return null;
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public boolean confirmOrderReceipt(String userId, String orderId) {
		if (StringTools.isEmpty(orderId)) {
			throw new BusinessException("订单不存在");
		}
		OrderInfo existing = orderInfoMapper.selectByOrderId(orderId);
		if (existing == null) {
			throw new BusinessException("订单不存在");
		}
		if (userId != null && !userId.equals(existing.getUserId())) {
			throw new BusinessException("订单不存在");
		}
		if (OrderStatusEnum.COMPLETED.getStatus().equals(existing.getOrderStatus())) {
			return false;
		}
		int rows = orderStateMachine.transition(orderId,
				Set.of(OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED),
				OrderStateEvent.CONFIRM_RECEIPT);
		if (rows == 0) {
			return false;
		}
		// 加销量要调 product 服务（远程调用），**不能放在事务里**：远程调用期间数据库
		// 连接一直被占着。自动收货任务每 10 分钟批量处理最多 100 单，每单都这样占连接，
		// 实测单连接被占用 18.1 秒；连接池（4 条）被抽干后，支付成功处理与 Outbox 投递
		// 一起失败（2026-10-05 压测实证：68 次支付处理失败 + 101 次投递失败 + 934 条 MQ 最终失败）。
		// 改为事务提交后再调：销量是派生数据，延迟几十毫秒无影响；且商品销售统计另有对账兜底。
		transactionalMqSender.sendAfterCommit(() -> increaseProductSalesForOrder(orderId));
		return true;
	}

	@Override
	public boolean cancelUnpaidOrderForPayTimeout(String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			return true;
		}
		if (!Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.WAIT_PAYMENT.getStatus())) {
			return true;
		}
		String payId = orderInfo.getPayOrderId();
		if (payId != null) {
			List<OrderInfo> orderInfoList = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payId);
			for (OrderInfo order : orderInfoList) {
				if (OrderFacts.isPaidOrBeyond(order.getOrderStatus())) {
					return true;
				}
			}
		}
		try {
			cancelOrder(null, orderId, OrderStatusEnum.CLOSED);
		} catch (PayOrderLifecycleBusyException e) {
			log.warn("支付超时关单生命周期锁忙，稍后 requeue orderId={}", orderId);
			return false;
		}
		return true;
	}

	private void increaseProductSalesForOrder(String orderId) {
		OrderItemQuery itemQuery = new OrderItemQuery();
		itemQuery.setOrderId(orderId);
		List<OrderItem> items = orderItemMapper.selectList(itemQuery);
		if (items == null || items.isEmpty()) {
			log.warn("确认收货无商品明细 orderId={}", orderId);
			return;
		}
		Map<String, Integer> qtyByProduct = new HashMap<>();
		for (OrderItem item : items) {
			if (StringTools.isEmpty(item.getProductId()) || item.getBuyCount() == null) {
				continue;
			}
			qtyByProduct.merge(item.getProductId(), item.getBuyCount(), Integer::sum);
		}
		for (Map.Entry<String, Integer> entry : qtyByProduct.entrySet()) {
			try {
				productRpcSupport.increaseSales(entry.getKey(), entry.getValue());
			} catch (BusinessException e) {
				log.warn("确认收货加销量跳过 productId={}, msg={}", entry.getKey(), e.getMessage());
			}
		}
	}
}
