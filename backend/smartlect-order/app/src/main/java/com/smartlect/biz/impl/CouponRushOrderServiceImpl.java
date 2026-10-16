package com.smartlect.biz.impl;

import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.enums.OrderFromTypeEnum;
import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.enums.RushingCouponStatusEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.biz.OrderRequestIdempotencyService;
import com.smartlect.component.CouponRushRedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.OrderPayAmountUtil;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;
import java.util.Map;

/**
 * 优惠券秒杀下单实现。
 * <p>Redis 预占是资格的唯一来源：预占成功后的任何一步失败，都必须把预占放回去，
 * 否则库存会被一直挂在一个不存在的订单上。下面每处 releaseRush* 调用都是为了这个。
 */
@Service("couponRushOrderService")
@Slf4j
public class CouponRushOrderServiceImpl implements CouponRushOrderService {

	@Resource
	private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;

	@Resource
	private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;

	@Resource
	private OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;

	@Resource
	private CouponRpcSupport couponRpcSupport;

	@Resource
	private PayRpcSupport payRpcSupport;

@Resource
private CouponRushRedisComponent couponRushRedisComponent;

	@Resource
	private AppConfig appConfig;

	@Resource
	private TransactionalMqSender transactionalMqSender;

	@Resource
	private OrderRequestIdempotencyService orderRequestIdempotencyService;

	@Resource
	private org.springframework.transaction.support.TransactionTemplate transactionTemplate;

	// 事务模型（ADR-0019，对齐 postOrder 三阶段）：旧实现两个入口整体 @Transactional，
	// 把 Lua 预占/远程锁资源/建支付意图等远程调用全部包进本地事务（普通下单路径已修掉的
	// RPC-in-TX 反模式）。现改为：只读校验在事务外 → Redis/远程预占在事务外 →
	// 订单/关系/明细 + RUSH_TIMEOUT Outbox 消息收进 TransactionTemplate 短本地事务 →
	// 创建占位券等远程写在事务外，失败走 releaseRush* 补偿或由超时关单收敛。
	@Override
	public CouponRushPrepareDTO prepareCouponRush(String userId, String couponId, String idempotencyKey) {
		return orderRequestIdempotencyService.execute(
				userId,
				OrderRequestIdempotencyService.COMMAND_COUPON_RUSH_PREPARE,
				idempotencyKey,
				Map.of("couponId", couponId),
				CouponRushPrepareDTO.class,
				() -> createCouponRushReservation(userId, couponId));
	}

	@Override
	public PayInfoDTO postCouponRushOrder(String userId, String couponId, String payMethod, String idempotencyKey) {
		return orderRequestIdempotencyService.execute(
				userId,
				OrderRequestIdempotencyService.COMMAND_COUPON_RUSH_PAY,
				idempotencyKey,
				Map.of("couponId", couponId, "payMethod", payMethod),
				PayInfoDTO.class,
				() -> createCouponRushPayment(userId, couponId, payMethod));
	}

	private CouponRushPrepareDTO createCouponRushReservation(String userId, String couponId) {
		// Phase 1: 只读校验（远程，不占本地连接）
		DiscountCouponVO discountCoupon = validateCouponRush(couponId);
		String userCouponId = StringTools.createUserCouponId();
		BigDecimal payAmount = new BigDecimal(Constants.RUSHING_COUPON_PAY_AMOUNT);

		// Phase 2: Redis 预占 + 远程库存扣减（各自事务，本地不持连接）
		int rushCode = couponRushRedisComponent.rushingCoupon(couponId, userId, userCouponId);
		if (rushCode == 1) {
			couponRpcSupport.syncRushStockFromDbIfRedisZero(couponId);
			throw new BusinessException("库存不足！");
		}
		assertRushCode(rushCode);

		try {
			DiscountCouponVO lockedCoupon = couponRpcSupport.getCoupon(couponId);
			boolean unlimited = lockedCoupon != null && lockedCoupon.isUnlimitedStock();
			if (lockedCoupon == null
					|| (!unlimited && (lockedCoupon.getRemainCount() == null || lockedCoupon.getRemainCount() <= 0))) {
				couponRpcSupport.releaseRushRedisReserve(couponId, userId);
				throw new BusinessException("库存不足");
			}

			int affected = couponRpcSupport.deductStock(couponId, userId);
			if (affected == 0) {
				couponRpcSupport.releaseRushRedisReserve(couponId, userId);
				throw new BusinessException("库存不足或并发冲突");
			}
			couponRpcSupport.invalidateCouponCache(couponId);

			// Phase 3: 短本地事务建单（order + rel + item + RUSH_TIMEOUT Outbox 原子落库，零远程调用）。
			// 曾经的 @Transactional 整体包裹既占连接又把远程调用卷进本地事务；
			// 关单消息必须与订单同事务（ADR-0018 同款约束），否则会重演孤儿订单窗口。
			OrderInfo orderInfo;
			try {
				orderInfo = transactionTemplate.execute(status ->
						insertCouponRushOrder(userId, couponId, userCouponId, discountCoupon, payAmount));
			} catch (Exception e) {
				couponRpcSupport.releaseRushCouponReserve(couponId, userId);
				if (e instanceof BusinessException businessException) {
					throw businessException;
				}
				log.error("优惠券秒杀建单失败 couponId={}, userId={}", couponId, userId, e);
				throw new BusinessException("下单失败，请稍后重试");
			}

			// Phase 4: 事务外远程写——创建占位券（CANT，支付成功才激活）。
			// 失败时订单已带 RUSH_TIMEOUT 消息：15 分钟超时关单会释放预占并关闭订单，自动收敛；
			// 这里同步补偿 release 加速收敛，不留下挂着预占的僵尸资格。
			try {
				UserCouponCreateDTO createDTO = new UserCouponCreateDTO();
				createDTO.setUserCouponId(userCouponId);
				createDTO.setUserId(userId);
				createDTO.setCouponId(couponId);
				createDTO.setStatus(UserCouponStatusEnum.CANT.getStatus());
				couponRpcSupport.createUserCoupon(createDTO);
			} catch (Exception e) {
				couponRpcSupport.releaseRushCouponReserve(couponId, userId);
				log.error("优惠券秒杀创建占位券失败，订单交由超时关单收敛 couponId={}, orderId={}",
						couponId, orderInfo.getOrderId(), e);
				throw new BusinessException("下单失败，请稍后重试");
			}

			long payExpireAt = orderInfo.getOrderTime().getTime() + appConfig.getOrderExpireMinute() * 60 * 1000L;

			CouponRushPrepareDTO dto = new CouponRushPrepareDTO();
			dto.setCouponId(couponId);
			dto.setUserCouponId(userCouponId);
			dto.setCouponName(discountCoupon.getCouponName());
			dto.setPayAmount(payAmount);
			dto.setOrderId(orderInfo.getOrderId());
			dto.setPayOrderId(orderInfo.getPayOrderId());
			dto.setPayExpireAt(payExpireAt);
			log.info("优惠券秒杀预占并建单成功 couponId={}, orderId={}", couponId, orderInfo.getOrderId());
			return dto;
		} finally {
			couponRpcSupport.syncRushStockFromDbIfRedisZero(couponId);
		}
	}

	private PayInfoDTO createCouponRushPayment(String userId, String couponId, String payMethod) {
		// 只读校验（远程/Redis/DB 读）全程无事务
		PayChannelEnum payChannelEnum = PayChannelEnum.resolve(payMethod);
		if (payChannelEnum == null) {
			throw new BusinessException("支付方式无效");
		}
		couponRpcSupport.assertRushNotBlocked(couponId);

		String userCouponId = couponRushRedisComponent.getRushUserCouponId(userId, couponId);
		if (StringTools.isEmpty(userCouponId)) {
			throw new BusinessException("抢购资格已失效，请返回重新抢购");
		}

		DiscountCouponVO discountCoupon = couponRpcSupport.getCoupon(couponId);
		if (discountCoupon == null) {
			throw new BusinessException("优惠券不存在");
		}

		OrderInfo orderInfo = findCouponRushOrderByUserCoupon(userCouponId);
		if (orderInfo == null || !userId.equals(orderInfo.getUserId())) {
			throw new BusinessException("订单不存在，请返回重新抢购");
		}
		if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
			if (OrderStatusEnum.CLOSED.getStatus().equals(orderInfo.getOrderStatus())
					|| OrderStatusEnum.CANCELLED.getStatus().equals(orderInfo.getOrderStatus())) {
				throw new BusinessException("订单已关闭，请重新抢购");
			}
			throw new BusinessException("当前订单已支付");
		}

		// 唯一本地写：待付款条件更新支付渠道（单条条件 UPDATE 自身原子，无需外层事务）
		OrderInfo updatePay = new OrderInfo();
		updatePay.setPayChannel(payMethod);
		OrderInfoQuery payUpdateQuery = new OrderInfoQuery();
		payUpdateQuery.setOrderId(orderInfo.getOrderId());
		payUpdateQuery.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
		orderInfoMapper.updateByParam(updatePay, payUpdateQuery);

		// 事务外远程写（幂等）
		orderInfo.setPayChannel(payMethod);
		BigDecimal payAmount = OrderPayAmountUtil.normalizeChannelPayAmount(orderInfo.getAmount());
		PayInfoDTO payInfoDTO = payRpcSupport.getPayUrl(
				payChannelEnum.getPayScene(), orderInfo.getPayOrderId(), orderInfo.getSubject(), payAmount, userId);
		payInfoDTO.setOrderId(orderInfo.getOrderId());
		payRpcSupport.createPending(userId, orderInfo.getPayOrderId(), orderInfo.getOrderId(),
				payAmount, payMethod);
		log.info("优惠券秒杀发起支付 orderId={}, payOrderId={}", orderInfo.getOrderId(), orderInfo.getPayOrderId());
		return payInfoDTO;
	}

	private DiscountCouponVO validateCouponRush(String couponId) {
		DiscountCouponVO discountCoupon = couponRpcSupport.getCoupon(couponId);
		if (discountCoupon == null) {
			throw new BusinessException("优惠券不存在");
		}
		if (RushingCouponStatusEnum.NO.getStatus().equals(discountCoupon.getRushingstatus())) {
			throw new BusinessException("该优惠券不是抢购状态");
		}
		Date now = new Date();
		if (discountCoupon.getRushingStartTime() != null && now.before(discountCoupon.getRushingStartTime())) {
			throw new BusinessException("该优惠券未开始抢购");
		}
		if (discountCoupon.getRushingEndTime() != null && now.after(discountCoupon.getRushingEndTime())) {
			throw new BusinessException("该优惠券已结束抢购");
		}
		couponRpcSupport.assertRushNotBlocked(couponId);
		if (!couponRpcSupport.hasAvailableRushStock(couponId)) {
			couponRpcSupport.syncRushStockFromDbIfRedisZero(couponId);
			if (!couponRpcSupport.hasAvailableRushStock(couponId)) {
				throw new BusinessException("库存不足！");
			}
		}
		return discountCoupon;
	}

	/**
	 * Lua 预占脚本的返回码，含义由 RedisComponent#rushingCoupon 定义。
	 */
	private void assertRushCode(int rushCode) {
		if (rushCode == 1) {
			throw new BusinessException("库存不足！");
		}
		if (rushCode == 2) {
			throw new BusinessException("不能重复下单！");
		}
		if (rushCode == 3) {
			throw new BusinessException("网络异常，请稍后再试~");
		}
	}

	private String buildCouponRushOrderSubject(String couponName) {
		String name = StringTools.isEmpty(couponName) ? "优惠券" : couponName.trim();
		return Constants.COUPON_RUSH_ORDER_SUBJECT_PREFIX + name;
	}

	/**
	 * 短本地事务内的纯 DB 写（由调用方的 TransactionTemplate 包裹执行）：
	 * order_info + order_coupon_rel + order_item + RUSH_TIMEOUT Outbox 消息原子落库。
	 * 零远程调用——创建占位券（远程）已移至事务外的 Phase 4。
	 */
	private OrderInfo insertCouponRushOrder(String userId, String couponId, String userCouponId,
			DiscountCouponVO discountCoupon, BigDecimal payAmount) {
		Date now = new Date();
		String orderId = StringTools.createOrderId();
		String payOrderId = StringTools.createPayOrderId();

		OrderInfo orderInfo = new OrderInfo();
		orderInfo.setOrderId(orderId);
		orderInfo.setAmount(payAmount);
		orderInfo.setUserId(userId);
		orderInfo.setOrderTime(now);
		orderInfo.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
		orderInfo.setPayScene(String.valueOf(OrderFromTypeEnum.COUPON.getType()));
		orderInfo.setPayChannel(PayChannelEnum.MOCK.getPayScene());
		orderInfo.setPayOrderId(payOrderId);
		orderInfo.setSubject(buildCouponRushOrderSubject(discountCoupon.getCouponName()));
		orderInfoMapper.insert(orderInfo);

		OrderCouponRel rel = new OrderCouponRel();
		rel.setOrderId(orderId);
		rel.setUserCouponId(userCouponId);
		rel.setCouponId(couponId);
		rel.setDiscountAmount(payAmount);
		rel.setCreateTime(now);
		orderCouponRelMapper.insert(rel);

		OrderItem orderItem = new OrderItem();
		orderItem.setOrderItemId(orderId + "_1");
		orderItem.setOrderId(orderId);
		orderItem.setProductId(couponId);
		orderItem.setProductName(discountCoupon.getCouponName());
		orderItem.setPropertyValueIdHash("coupon_rush");
		orderItem.setPropertyInfo("优惠券秒杀");
		orderItem.setBuyCount(1);
		orderItem.setItemAmount(payAmount);
		orderItem.setOrderItemStatus(OrderItemStatusEnum.NORMAL.getStatus());
		orderItem.setCover("");
		orderItemMapper.insert(orderItem);

		// RUSH_TIMEOUT 关单消息与订单同事务写入 Outbox（对齐普通下单 Phase 3，ADR-0018/0019）：
		// 订单存在则必然有关单收敛路径，占位券失败也不会留下永久挂起的待付款单。
		// 载荷必须与消费端（RocketMqOrderDeadListListener，payloadType=RushingCouponMessageDTO）
		// 一致：此前发的是只填 orderId 的 PayOrderMessageDTO，消费端读到的 userId/couponId/
		// userCouponId 全是 null → "未建单/建单未落库/券存在订单缺失"三个回补分支全部空转，
		// Redis 预占只能等 TTL 回收（2026-10-16 审计 L10）。
		RushingCouponMessageDTO payTimeoutDto = new RushingCouponMessageDTO();
		payTimeoutDto.setOrderId(orderId);
		payTimeoutDto.setPayOrderId(payOrderId);
		payTimeoutDto.setUserId(userId);
		payTimeoutDto.setCouponId(couponId);
		payTimeoutDto.setUserCouponId(userCouponId);
		transactionalMqSender.sendAfterCommit(
				RocketMqTopics.TOPIC_DELAY,
				RocketMqTopics.TAG_RUSH_TIMEOUT,
				payTimeoutDto,
				MqIdempotencyKeys.payTimeout(orderId),
				MessageReliabilityLevelEnum.STANDARD,
				System.currentTimeMillis() + RocketMqTopics.RUSH_EXPIRE.toMillis());
		log.info("优惠券秒杀订单已创建 orderId={}, payOrderId={}", orderId, payOrderId);
		return orderInfo;
	}

	private OrderInfo findCouponRushOrderByUserCoupon(String userCouponId) {
		if (StringTools.isEmpty(userCouponId)) {
			return null;
		}
		OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
		relQuery.setUserCouponId(userCouponId);
		List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
		if (rels == null || rels.isEmpty()) {
			return null;
		}
		return orderInfoMapper.selectByOrderId(rels.get(0).getOrderId());
	}

	@Override
	public void activateUserCoupon(String userId, String userCouponId) {
		if (StringTools.isEmpty(userCouponId) || StringTools.isEmpty(userId)) {
			return;
		}
		try {
			couponRpcSupport.changeUserCouponStatus(userCouponId, userId,
					UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(), null);
		} catch (BusinessException ignore) {
			// 幂等：已激活则忽略
		}
	}

	@Override
	public void syncPaidCouponRushUserCoupons(String userId) {
		OrderInfoQuery orderQuery = new OrderInfoQuery();
		orderQuery.setUserId(userId);
		orderQuery.setPayScene(String.valueOf(OrderFromTypeEnum.COUPON.getType()));
		orderQuery.setOrderStatusList(new Integer[]{
				OrderStatusEnum.PAID.getStatus(),
				OrderStatusEnum.SHIPPED.getStatus(),
				OrderStatusEnum.COMPLETED.getStatus()
		});
		List<OrderInfo> orders = orderInfoMapper.selectList(orderQuery);
		if (orders == null || orders.isEmpty()) {
			return;
		}
		int activated = 0;
		for (OrderInfo orderInfo : orders) {
			OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
			relQuery.setOrderId(orderInfo.getOrderId());
			List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
			for (OrderCouponRel rel : rels) {
				if (StringTools.isEmpty(rel.getUserCouponId())) {
					continue;
				}
				UserCouponVO uc = couponRpcSupport.getUserCoupon(rel.getUserCouponId());
				if (uc != null && UserCouponStatusEnum.CANT.getStatus().equals(uc.getStatus())) {
					activateUserCoupon(orderInfo.getUserId(), rel.getUserCouponId());
					activated++;
				}
			}
		}
		if (activated > 0) {
			log.info("同步秒杀已付订单用户券为未使用 userId={}, count={}", userId, activated);
		}
	}
}
