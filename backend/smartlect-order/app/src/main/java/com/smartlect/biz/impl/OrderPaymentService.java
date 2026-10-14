package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.api.enums.LogisticsStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.api.support.CouponFeignSupport;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.dto.LogisticsSendDTO;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.utils.StringTools;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Objects;

/**
 * 支付回调领域服务（ADR-0019，拆自 OrderInfoServiceImpl）。
 *
 * <p>事务模型（对齐 postOrder 三阶段纪律，ADR-0019）：旧实现整个 paySuccess 挂在
 * @Transactional 下，assertSettled/逐券核销/markSuccess 等远程调用全程占用数据库连接——
 * 与 2026-10-05 压测事故（连接池抽干）同型。现改为：
 * 远程读校验在事务外 → 物流补齐/状态机 CAS/LOGISTICS_STEP Outbox/实付分摊收进
 * TransactionTemplate 短本地事务（毫秒级，零远程调用）→ 券核销与 markSuccess 在事务外
 * 幂等执行，失败由支付事件重投驱动重试（状态机 CAS 保证重入安全）。
 */
@Service
@Slf4j
public class OrderPaymentService {

    private final OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    private final OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    private final OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;
    private final OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    private final TransactionTemplate transactionTemplate;
    private final OrderStateMachine orderStateMachine;
    private final RedisComponent redisComponent;
    private final PayOrderRedisComponent payOrderRedisComponent;
    private final PayFeignSupport payFeignSupport;
    private final CouponFeignSupport couponFeignSupport;
    private final CouponRushOrderService couponRushOrderService;
    private final TransactionalMqSender transactionalMqSender;

    public OrderPaymentService(
            OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper,
            OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper,
            OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper,
            OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper,
            TransactionTemplate transactionTemplate,
            OrderStateMachine orderStateMachine,
            RedisComponent redisComponent,
            PayOrderRedisComponent payOrderRedisComponent,
            PayFeignSupport payFeignSupport,
            CouponFeignSupport couponFeignSupport,
            CouponRushOrderService couponRushOrderService,
            TransactionalMqSender transactionalMqSender) {
        this.orderInfoMapper = orderInfoMapper;
        this.orderItemMapper = orderItemMapper;
        this.orderLogisticsInfoMapper = orderLogisticsInfoMapper;
        this.orderCouponRelMapper = orderCouponRelMapper;
        this.transactionTemplate = transactionTemplate;
        this.orderStateMachine = orderStateMachine;
        this.redisComponent = redisComponent;
        this.payOrderRedisComponent = payOrderRedisComponent;
        this.payFeignSupport = payFeignSupport;
        this.couponFeignSupport = couponFeignSupport;
        this.couponRushOrderService = couponRushOrderService;
        this.transactionalMqSender = transactionalMqSender;
    }

    // 支付成功信息：不加 @Transactional——短本地事务在 paySuccessInLock 内部按需开启，
    // 生命周期锁覆盖整个处理序列（含事务外远程步骤）。
    public void paySuccess(PayOrderNotifyDTO payOrderNotifyDTO) {
        if (payOrderNotifyDTO == null || StringTools.isEmpty(payOrderNotifyDTO.getPayOrderId())) {
            throw new BusinessException("支付订单号无效");
        }
        String payOrderId = payOrderNotifyDTO.getPayOrderId();
        payOrderRedisComponent.runWithPayOrderLifecycleLock(payOrderId,
                () -> paySuccessInLock(payOrderNotifyDTO));
    }

    private void paySuccessInLock(PayOrderNotifyDTO payOrderNotifyDTO) {
        String payOrderId = payOrderNotifyDTO.getPayOrderId();
        // 远程读校验：事务外（不占本地连接）
        payFeignSupport.assertSettled(payOrderId);
        List<OrderInfo> orderInfoList = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payOrderId);
        if (orderInfoList.isEmpty()) {
            throw new BusinessException("订单不存在");
        }
        if (orderInfoList.stream().anyMatch(OrderFacts::isCouponRushOrder)) {
            paySuccessForCouponRush(orderInfoList, payOrderNotifyDTO);
            return;
        }
        if (orderInfoList.stream().allMatch(o -> OrderFacts.isPaidOrBeyond(o.getOrderStatus()))) {
            log.info("paySuccess 幂等跳过 payOrderId={}", payOrderId);
            return;
        }
        if (orderInfoList.stream().anyMatch(o -> OrderFacts.isClosedOrCancelled(o.getOrderStatus()))) {
            handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
            return;
        }

        // 短本地事务：物流补齐 + 状态机 CAS + LOGISTICS_STEP Outbox + 实付分摊（纯 DB，毫秒级）
        Integer updatedCount = transactionTemplate.execute(status -> {
            upsertLogisticsForOrders(orderInfoList);
            int count = 0;
            for (OrderInfo orderInfo : orderInfoList) {
                orderInfo.setChannelOrderId(payOrderNotifyDTO.getChannelOrderId());
                orderInfo.setOrderStatus(OrderStatusEnum.PAID.getStatus());
                int rows = orderStateMachine.transition(orderInfo.getOrderId(), OrderStatusEnum.WAIT_PAYMENT,
                        OrderStateEvent.PAY_SUCCESS, orderInfo);
                if (rows > 0) {
                    count++;
                    PayOrderMessageDTO dto = new PayOrderMessageDTO();
                    dto.setOrderId(orderInfo.getOrderId());
                    dto.setLogisticsStep(0);
                    transactionalMqSender.sendAfterCommit(
                            RocketMqTopics.TOPIC_DELAY,
                            RocketMqTopics.TAG_LOGISTICS_STEP,
                            dto,
                            MqIdempotencyKeys.payLogistics(orderInfo.getOrderId(), 0),
                            MessageReliabilityLevelEnum.STANDARD,
                            System.currentTimeMillis() + RocketMqTopics.LOGISTICS_STEP.toMillis());
                }
            }
            if (count > 0) {
                if (count < orderInfoList.size()) {
                    throw new BusinessException("支付成功处理失败，部分订单状态异常");
                }
                recordPaymentOutcomes(orderInfoList, payOrderId);
            }
            return count;
        });
        if (updatedCount == null || updatedCount == 0) {
            handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
            return;
        }

        // 事务外远程写（幂等）：券核销失败抛出由支付事件重投重试；markSuccess 在 mock 渠道
        // 已由 completePayment 先行标记，此处为幂等双保险。
        useCouponIfNeeded(orderInfoList);
        payFeignSupport.markSuccess(payOrderId, payOrderNotifyDTO.getChannelOrderId());
    }

    private void upsertLogisticsForOrders(List<OrderInfo> orderInfoList) {
        // 获取同一payOrderId下的订单中不为null的收货信息
        OrderLogisticsInfo logisticsInfo = new OrderLogisticsInfo();
        // 根据orderId查询不为null的收货信息
        for (OrderInfo orderInfo : orderInfoList) {
            if (orderInfo == null) {
                throw new BusinessException("订单不存在");
            }
            String orderId = orderInfo.getOrderId();
            logisticsInfo = orderLogisticsInfoMapper.selectByOrderId(orderId);
            if (logisticsInfo == null) {
                continue;
            }
            break;
        }
        // 从redis中获得默认发货信息
        LogisticsSendDTO sendLogisticsSendDTO = redisComponent.getLogisticsInfo();
        // 把所有同一payOrderId下的订单都设置同样的收货信息
        for (OrderInfo orderInfo : orderInfoList) {
            // 根据orderId查询物流Info
            OrderLogisticsInfo orderLogisticsInfo = orderLogisticsInfoMapper.selectByOrderId(orderInfo.getOrderId());
            if (orderLogisticsInfo == null) {
                // 如果没有则插入
                orderLogisticsInfo = new OrderLogisticsInfo();
                orderLogisticsInfo.setOrderId(orderInfo.getOrderId());
                orderLogisticsInfo.setUserId(orderInfo.getUserId());
                orderLogisticsInfo.setReceiverName(logisticsInfo.getReceiverName());
                orderLogisticsInfo.setReceiverPhone(logisticsInfo.getReceiverPhone());
                orderLogisticsInfo.setReceiverAddress(logisticsInfo.getReceiverAddress());
                orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.PENDING_SHIPMENT.getStatus());
                if (sendLogisticsSendDTO != null) {
                    orderLogisticsInfo.setSenderName(sendLogisticsSendDTO.getSenderName());
                    orderLogisticsInfo.setSenderPhone(sendLogisticsSendDTO.getSenderPhone());
                    orderLogisticsInfo.setSenderAddress(sendLogisticsSendDTO.getSenderAddress());
                }
                orderLogisticsInfoMapper.insert(orderLogisticsInfo);
            } else {
                // 更新
                OrderLogisticsInfoQuery orderLogisticsInfoQuery = new OrderLogisticsInfoQuery();
                orderLogisticsInfoQuery.setOrderId(orderInfo.getOrderId());
                orderLogisticsInfoQuery.setUserId(orderInfo.getUserId());
                orderLogisticsInfo.setReceiverName(logisticsInfo.getReceiverName());
                orderLogisticsInfo.setReceiverPhone(logisticsInfo.getReceiverPhone());
                orderLogisticsInfo.setReceiverAddress(logisticsInfo.getReceiverAddress());
                if (sendLogisticsSendDTO != null) {
                    orderLogisticsInfo.setSenderName(sendLogisticsSendDTO.getSenderName());
                    orderLogisticsInfo.setSenderPhone(sendLogisticsSendDTO.getSenderPhone());
                    orderLogisticsInfo.setSenderAddress(sendLogisticsSendDTO.getSenderAddress());
                }
                orderLogisticsInfoMapper.updateByParam(orderLogisticsInfo, orderLogisticsInfoQuery);
            }
        }
    }

    private void paySuccessForCouponRush(List<OrderInfo> orderInfoList, PayOrderNotifyDTO payOrderNotifyDTO) {
        String payOrderId = payOrderNotifyDTO.getPayOrderId();
        if (orderInfoList.stream().allMatch(o -> OrderStatusEnum.COMPLETED.getStatus().equals(o.getOrderStatus()))) {
            log.info("couponRush paySuccess 幂等跳过 payOrderId={}", payOrderId);
            return;
        }
        if (orderInfoList.stream().anyMatch(o -> OrderFacts.isClosedOrCancelled(o.getOrderStatus()))) {
            handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
            return;
        }
        // 短本地事务：状态机 CAS 翻单 + 读取待激活券关系（券激活是远程调用，放事务外）
        List<CouponActivation> pendingActivation = new ArrayList<>();
        Integer updatedCount = transactionTemplate.execute(status -> {
            int count = 0;
            for (OrderInfo orderInfo : orderInfoList) {
                orderInfo.setChannelOrderId(payOrderNotifyDTO.getChannelOrderId());
                orderInfo.setOrderStatus(OrderStatusEnum.COMPLETED.getStatus());
                int rows = orderStateMachine.transition(orderInfo.getOrderId(), OrderStatusEnum.WAIT_PAYMENT,
                        OrderStateEvent.COUPON_RUSH_PAY_SUCCESS, orderInfo);
                if (rows == 0) {
                    continue;
                }
                count++;
                OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
                relQuery.setOrderId(orderInfo.getOrderId());
                for (OrderCouponRel rel : orderCouponRelMapper.selectList(relQuery)) {
                    pendingActivation.add(new CouponActivation(orderInfo.getUserId(), rel.getUserCouponId()));
                }
            }
            if (count > 0 && count < orderInfoList.size()) {
                throw new BusinessException("支付成功处理失败，部分订单状态异常");
            }
            return count;
        });
        if (updatedCount == null || updatedCount == 0) {
            handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
            return;
        }
        // 事务外远程写：券激活（幂等）；失败抛出由支付事件重投驱动重试
        for (CouponActivation activation : pendingActivation) {
            couponRushOrderService.activateUserCoupon(activation.userId(), activation.userCouponId());
        }
        payFeignSupport.markSuccess(payOrderId, payOrderNotifyDTO.getChannelOrderId());
        log.info("优惠券秒杀支付成功 payOrderId={}, 券数量={}", payOrderId, orderInfoList.size());
    }

    private record CouponActivation(String userId, String userCouponId) { }

    private void handlePaySuccessConflict(String payOrderId, PayOrderNotifyDTO payOrderNotifyDTO) {
        List<OrderInfo> latest = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payOrderId);
        if (latest.isEmpty()) {
            throw new BusinessException("订单不存在");
        }
        if (latest.stream().allMatch(o -> OrderFacts.isPaidOrBeyond(o.getOrderStatus())
                || OrderStatusEnum.COMPLETED.getStatus().equals(o.getOrderStatus()))) {
            log.info("paySuccess 幂等跳过 payOrderId={}", payOrderId);
            return;
        }
        if (latest.stream().anyMatch(o -> OrderFacts.isClosedOrCancelled(o.getOrderStatus()))) {
            refundLatePaymentAfterClose(payOrderId, payOrderNotifyDTO, latest);
            return;
        }
        throw new BusinessException("支付成功处理失败，订单状态异常");
    }

    private void refundLatePaymentAfterClose(String payOrderId, PayOrderNotifyDTO payOrderNotifyDTO,
            List<OrderInfo> orders) {
        if (!payOrderRedisComponent.tryMarkLatePaymentRefundOnce(payOrderId)) {
            log.info("关单后迟到支付退款幂等跳过 payOrderId={}", payOrderId);
            return;
        }
        BigDecimal total = orders.stream()
                .map(OrderInfo::getAmount)
                .filter(Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        if (total.compareTo(BigDecimal.ZERO) <= 0) {
            log.warn("关单后迟到支付退款金额为0 payOrderId={}", payOrderId);
            return;
        }
        OrderInfo refOrder = orders.get(0);
        PayChannelEnum payChannelEnum = resolveWaitPayChannel(refOrder);
        String refundRequestNo = "LATE" + StringTools.getRandomNumber(Constants.LENGTH_30);
        try {
            payFeignSupport.refund(payOrderId, refundRequestNo, total, payChannelEnum.getPayScene());
            payFeignSupport.markRefunded(payOrderId);
            log.warn("关单后迟到的支付已原路退款 payOrderId={}, channelOrderId={}, amount={}",
                    payOrderId, payOrderNotifyDTO.getChannelOrderId(), total);
        } catch (Exception e) {
            payOrderRedisComponent.clearLatePaymentRefundMark(payOrderId);
            throw new BusinessException("关单后支付退款失败：" + e.getMessage(), e);
        }
    }

    private void useCouponIfNeeded(List<OrderInfo> orderInfoList) {
        if (orderInfoList == null || orderInfoList.isEmpty()) {
            return;
        }
        Date now = new Date();
        for (OrderInfo o : orderInfoList) {
            OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
            relQuery.setOrderId(o.getOrderId());
            List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
            for (OrderCouponRel rel : rels) {
                if (StringTools.isEmpty(rel.getUserCouponId())) {
                    continue;
                }
                try {
                    couponFeignSupport.changeUserCouponStatus(rel.getUserCouponId(), o.getUserId(),
                            UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.USED.getStatus(), now);
                } catch (BusinessException ex) {
                    // 幂等：券已是 USED 时忽略；其它业务失败需抛出以便支付回调重试
                    com.smartlect.api.vo.UserCouponVO uc = null;
                    try {
                        uc = couponFeignSupport.getUserCoupon(rel.getUserCouponId());
                    } catch (Exception ignore) {
                    }
                    if (uc != null && UserCouponStatusEnum.USED.getStatus().equals(uc.getStatus())) {
                        continue;
                    }
                    log.error("支付成功后核销优惠券失败, orderId={}, userCouponId={}, msg={}",
                            o.getOrderId(), rel.getUserCouponId(), ex.getMessage());
                    throw ex;
                }
            }
        }
    }

    /**
     * 支付成功后按原价权重把订单实付分摊到明细（累计取整，末行吸收分差），并做金额不变量校验。
     * 随短本地事务执行：分摊结果与状态机翻单同事务提交，失败即整体回滚。
     */
    void recordPaymentOutcomes(List<OrderInfo> orders, String payOrderId) {
        if (orders == null || orders.isEmpty()) {
            return;
        }
        for (OrderInfo order : orders) {
            List<OrderItem> items = new ArrayList<>(loadOrderItems(order.getOrderId()));
            items.sort(Comparator.comparing(OrderItem::getOrderItemId));
            if (items.isEmpty()) {
                continue;
            }
            BigDecimal grossTotal = items.stream().map(item -> normalizeMoney(item.getItemAmount()))
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            BigDecimal orderPaid = normalizeMoney(order.getAmount());
            if (orderPaid.compareTo(grossTotal) > 0) {
                throw new BusinessException("订单实付超过商品原价合计");
            }
            BigDecimal cumulativeGross = BigDecimal.ZERO;
            BigDecimal allocated = BigDecimal.ZERO;
            for (int index = 0; index < items.size(); index++) {
                OrderItem item = items.get(index);
                cumulativeGross = cumulativeGross.add(item.getItemAmount());
                // Fixed payment basis; cumulative rounding prevents a tiny final line absorbing excess cents.
                BigDecimal cumulativePaid = index == items.size() - 1 || grossTotal.signum() == 0
                        ? orderPaid
                        : orderPaid.multiply(cumulativeGross).divide(grossTotal, 2, RoundingMode.HALF_UP);
                BigDecimal paidAmount = cumulativePaid.subtract(allocated).setScale(2);
                allocated = cumulativePaid;
                if (item.getPaidAmount() == null) {
                    if (orderItemMapper.recordPaidAmount(item.getOrderItemId(), paidAmount) != 1) {
                        throw new BusinessException("订单明细实付保存失败");
                    }
                    item.setPaidAmount(paidAmount);
                } else if (item.getPaidAmount().compareTo(paidAmount) != 0) {
                    throw new BusinessException("订单明细实付与已确认金额不一致");
                }
            }
        }
    }

    private List<OrderItem> loadOrderItems(String orderId) {
        if (StringTools.isEmpty(orderId)) {
            return java.util.Collections.emptyList();
        }
        OrderItemQuery query = new OrderItemQuery();
        query.setOrderId(orderId);
        List<OrderItem> items = orderItemMapper.selectList(query);
        return items == null ? java.util.Collections.emptyList() : items;
    }

    private BigDecimal normalizeMoney(BigDecimal amount) {
        if (amount == null || amount.signum() < 0) {
            throw new BusinessException("订单金额必须为非负金额");
        }
        try {
            return amount.setScale(2, RoundingMode.UNNECESSARY);
        } catch (ArithmeticException exception) {
            throw new BusinessException("订单金额必须精确到分");
        }
    }

    /** 待支付单的渠道兜底（缺失时补写 MOCK 渠道，条件更新防越权改已支付单）。 */
    PayChannelEnum resolveWaitPayChannel(OrderInfo orderInfo) {
        PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
        if (payChannelEnum != null) {
            return payChannelEnum;
        }
        payChannelEnum = PayChannelEnum.MOCK;
        OrderInfo patch = new OrderInfo();
        patch.setPayChannel(payChannelEnum.getPayScene());
        OrderInfoQuery patchQuery = new OrderInfoQuery();
        patchQuery.setOrderId(orderInfo.getOrderId());
        patchQuery.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
        orderInfoMapper.updateByParam(patch, patchQuery);
        orderInfo.setPayChannel(payChannelEnum.getPayScene());
        return payChannelEnum;
    }
}
