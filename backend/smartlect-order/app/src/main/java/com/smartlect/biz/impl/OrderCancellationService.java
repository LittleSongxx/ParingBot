package com.smartlect.biz.impl;

import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.api.support.CouponFeignSupport;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.api.support.StockFeignSupport;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RemoteCompensateRecorder;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.utils.StringTools;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * 取消/关单领域服务（ADR-0019，拆自 OrderInfoServiceImpl）。
 *
 * <p>事务模型（对齐 postOrder 三阶段纪律）：旧实现整个 cancelOrder 挂在 @Transactional 下，
 * markClosed/渠道关单/解券/库存回补等远程调用全程占连接。现改为每条路径都是
 * 「读校验（无事务）→ TransactionTemplate 短本地事务做状态机 CAS 关单 → 事务外幂等远程写
 * （失败走补偿台账或由关单消息重投收敛）」。生命周期锁覆盖整段处理序列。
 */
@Service
@Slf4j
public class OrderCancellationService {

    private final OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    private final OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    private final OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    private final TransactionTemplate transactionTemplate;
    private final OrderStateMachine orderStateMachine;
    private final PayOrderRedisComponent payOrderRedisComponent;
    private final PayFeignSupport payFeignSupport;
    private final StockFeignSupport stockFeignSupport;
    private final CouponFeignSupport couponFeignSupport;
    private final RemoteCompensateRecorder remoteCompensateRecorder;

    public OrderCancellationService(
            OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper,
            OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper,
            OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper,
            TransactionTemplate transactionTemplate,
            OrderStateMachine orderStateMachine,
            PayOrderRedisComponent payOrderRedisComponent,
            PayFeignSupport payFeignSupport,
            StockFeignSupport stockFeignSupport,
            CouponFeignSupport couponFeignSupport,
            RemoteCompensateRecorder remoteCompensateRecorder) {
        this.orderInfoMapper = orderInfoMapper;
        this.orderItemMapper = orderItemMapper;
        this.orderCouponRelMapper = orderCouponRelMapper;
        this.transactionTemplate = transactionTemplate;
        this.orderStateMachine = orderStateMachine;
        this.payOrderRedisComponent = payOrderRedisComponent;
        this.payFeignSupport = payFeignSupport;
        this.stockFeignSupport = stockFeignSupport;
        this.couponFeignSupport = couponFeignSupport;
        this.remoteCompensateRecorder = remoteCompensateRecorder;
    }

    // 取消订单：不加 @Transactional——CAS 关单在 cancelOrderInLock 内的短事务完成，
    // 远程副作用（markClosed/渠道关单/解券/回补库存）在事务外幂等执行。
    public void cancelOrder(String userId, String orderId, OrderStatusEnum orderStatusEnum) {
        OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
        if (orderInfo == null) {
            throw new BusinessException("订单不存在");
        }
        String payOrderId = orderInfo.getPayOrderId();
        if (StringTools.isEmpty(payOrderId)) {
            cancelOrderInLock(userId, orderId);
            return;
        }
        payOrderRedisComponent.runWithPayOrderLifecycleLock(payOrderId, () -> cancelOrderInLock(userId, orderId));
    }

    private void cancelOrderInLock(String userId, String orderId) {
        OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
        if (orderInfo == null) {
            throw new BusinessException("订单不存在");
        }
        if (userId != null && !orderInfo.getUserId().equals(userId)) {
            throw new BusinessException("订单不存在");
        }
        if (OrderFacts.isCouponRushOrder(orderInfo)) {
            if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
                throw new BusinessException("当前订单状态不能取消");
            }
            cancelCouponRushOrder(orderId, userId);
            return;
        }
        if (userId == null && !StringTools.isEmpty(orderInfo.getPayOrderId())) {
            closeUnpaidPayOrderForTimeout(orderInfo.getPayOrderId());
            return;
        }
        if (!StringTools.isEmpty(orderInfo.getPayOrderId())) {
            cancelUnpaidPayOrderForUser(userId, orderInfo.getPayOrderId());
            return;
        }
        if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
            throw new BusinessException("当前订单状态不能取消");
        }
        OrderStateEvent cancelEvent = userId != null ? OrderStateEvent.USER_CANCEL : OrderStateEvent.SYSTEM_CANCEL;
        // 短事务 CAS：仅状态机条件更新；库存回补在事务外（远程幂等 + 补偿台账）
        int rows = transactionTemplate.execute(status ->
                orderStateMachine.transition(orderId, OrderStatusEnum.WAIT_PAYMENT, cancelEvent));
        if (rows == 0) {
            if (userId != null) {
                throw new BusinessException("当前订单状态不能取消");
            }
            return;
        }
        restoreStockForOrders(orderId, List.of(orderInfo));
    }

    private void cancelUnpaidPayOrderForUser(String userId, String payOrderId) {
        List<OrderInfo> orderList = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payOrderId);
        if (orderList.isEmpty()
                || orderList.stream().anyMatch(order -> !Objects.equals(userId, order.getUserId()))) {
            throw new BusinessException("订单不存在");
        }
        if (orderList.stream().anyMatch(order -> OrderFacts.isPaidOrBeyond(order.getOrderStatus()))) {
            throw new BusinessException("当前支付单已支付无法取消");
        }
        if (orderList.stream().anyMatch(order ->
                !OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(order.getOrderStatus())
                        && !OrderFacts.isClosedOrCancelled(order.getOrderStatus()))) {
            throw new BusinessException("当前支付单状态不能取消");
        }
        List<OrderInfo> waitingOrders = orderList.stream()
                .filter(order -> OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(order.getOrderStatus()))
                .toList();
        if (waitingOrders.isEmpty()) {
            return;
        }
        if (waitingOrders.size() != orderList.size()) {
            throw new BusinessException("支付单内子订单状态不一致，请联系客服处理");
        }

        // 短事务 CAS：支付单维度批量条件更新
        int rows = transactionTemplate.execute(status -> orderStateMachine.transitionPayOrder(
                payOrderId, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.USER_CANCEL));
        if (rows != waitingOrders.size()) {
            throw new BusinessException("支付单取消失败，子订单状态已变化");
        }

        // 事务外远程收敛（幂等/可补偿）：单点失败不影响关单事实，重试路径按已关单幂等跳过
        markPayOrderClosedIfNeeded(payOrderId);
        payFeignSupport.markClosed(payOrderId);
        cancelOrder4Channel(waitingOrders.get(0));
        releaseCouponIfNeeded(payOrderId);
        restoreStockForOrders(payOrderId, waitingOrders);
    }

    private void closeUnpaidPayOrderForTimeout(String payOrderId) {
        List<OrderInfo> orderList = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payOrderId);
        if (orderList.isEmpty()) {
            return;
        }
        for (OrderInfo order : orderList) {
            if (OrderFacts.isPaidOrBeyond(order.getOrderStatus())) {
                log.info("支付超时关单跳过：存在已支付子单 payOrderId={}", payOrderId);
                return;
            }
        }
        // 短事务 CAS：支付单维度批量条件更新
        int rows = transactionTemplate.execute(status -> orderStateMachine.transitionPayOrder(
                payOrderId, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAYMENT_TIMEOUT));
        if (rows == 0) {
            log.info("支付超时关单无待付款子单 payOrderId={}", payOrderId);
            return;
        }
        if (rows != orderList.size()) {
            throw new BusinessException("支付超时关单失败，子订单状态已变化");
        }
        // 事务外远程收敛
        markPayOrderClosedIfNeeded(payOrderId);
        payFeignSupport.markClosed(payOrderId);
        OrderInfo channelRef = orderList.stream()
                .filter(o -> !StringTools.isEmpty(o.getChannelOrderId()))
                .findFirst()
                .orElse(orderList.get(0));
        cancelOrder4Channel(channelRef);
        releaseCouponIfNeeded(payOrderId);
        restoreStockForOrders(payOrderId, orderList);
    }

    private void cancelCouponRushOrder(String orderId, String userId) {
        OrderStateEvent cancelEvent = userId != null ? OrderStateEvent.USER_CANCEL : OrderStateEvent.SYSTEM_CANCEL;
        // 短事务 CAS：状态机条件更新；券释放是远程调用，放事务外
        int rows = transactionTemplate.execute(status ->
                orderStateMachine.transition(orderId, OrderStatusEnum.WAIT_PAYMENT, cancelEvent));
        if (rows == 0) {
            return;
        }
        OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
        if (orderInfo == null) {
            return;
        }
        markPayOrderClosedIfNeeded(orderInfo.getPayOrderId());
        OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
        relQuery.setOrderId(orderId);
        List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
        for (OrderCouponRel rel : rels) {
            if (!StringTools.isEmpty(rel.getCouponId())) {
                couponFeignSupport.releaseRushCouponReserve(rel.getCouponId(), orderInfo.getUserId());
            }
        }
    }

    void restoreStockForOrders(String restoreReferenceId, List<OrderInfo> orderList) {
        if (StringTools.isEmpty(restoreReferenceId) || orderList == null || orderList.isEmpty()) {
            return;
        }
        List<ProductItem> newList = new ArrayList<>();
        for (OrderInfo orderInfo1 : orderList) {
            OrderItemQuery orderItemQuery = new OrderItemQuery();
            orderItemQuery.setOrderId(orderInfo1.getOrderId());
            List<OrderItem> orderItemList = orderItemMapper.selectList(orderItemQuery);
            for (OrderItem orderItem : orderItemList) {
                ProductItem productItem = new ProductItem();
                productItem.setProductId(orderItem.getProductId());
                productItem.setPropertyValueIdHash(orderItem.getPropertyValueIdHash());
                productItem.setBuyCount(orderItem.getBuyCount());
                newList.add(productItem);
            }
        }
        if (newList.isEmpty()) {
            throw new BusinessException("商品列表为空");
        }
        try {
            stockFeignSupport.restoreOrderStock(restoreReferenceId, newList);
        } catch (Exception e) {
            log.error("关单库存回补失败, referenceId={}", restoreReferenceId, e);
            remoteCompensateRecorder.recordOrderStockRestore(restoreReferenceId, newList, e);
        }
    }

    private void releaseCouponIfNeeded(String payOrderId) {
        if (StringTools.isEmpty(payOrderId)) {
            return;
        }
        List<OrderInfo> orders = OrderFacts.loadOrdersByPayOrderId(orderInfoMapper, payOrderId);
        for (OrderInfo o : orders) {
            if (OrderFacts.isCouponRushOrder(o)) {
                continue;
            }
            OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
            relQuery.setOrderId(o.getOrderId());
            List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
            for (OrderCouponRel rel : rels) {
                if (StringTools.isEmpty(rel.getUserCouponId())) {
                    continue;
                }
                UserCouponVO uc = couponFeignSupport.getUserCoupon(rel.getUserCouponId());
                if (uc != null && UserCouponStatusEnum.CANT.getStatus().equals(uc.getStatus())) {
                    try {
                        couponFeignSupport.changeUserCouponStatus(uc.getUserCouponId(), uc.getUserId(),
                                UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(), null);
                    } catch (Exception compensateEx) {
                        log.error("关单优惠券解锁失败, payOrderId={}, userCouponId={}",
                                payOrderId, uc.getUserCouponId(), compensateEx);
                        remoteCompensateRecorder.recordCouponUnlock(
                                payOrderId, uc.getUserCouponId(), uc.getUserId(),
                                UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(),
                                compensateEx);
                    }
                }
            }
        }
    }

    private void markPayOrderClosedIfNeeded(String payOrderId) {
        if (!StringTools.isEmpty(payOrderId)) {
            payOrderRedisComponent.tryMarkPayOrderCloseOnce(payOrderId);
        }
    }

    // 关闭订单（支付系统官方）
    void cancelOrder4Channel(OrderInfo orderInfo) {
        PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
        if (payChannelEnum == null) {
            return;
        }
        payFeignSupport.closeOrder(orderInfo.getPayOrderId(), payChannelEnum.getPayScene());
    }
}
