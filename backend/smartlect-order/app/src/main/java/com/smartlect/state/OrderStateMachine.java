package com.smartlect.state;

import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderStatusLog;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderStatusLogMapper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/**
 * 订单状态机。状态规则与带旧状态条件的持久化更新（CAS）只能从这里发起：
 * 非法流转在解析目标状态时抛出，并发竞争表现为返回 0 行，由调用方决定后续动作。
 */
@Component
public class OrderStateMachine {

    private static final Map<OrderStatusEnum, Map<OrderStateEvent, OrderStatusEnum>> TRANSITIONS = buildTransitions();

    @Resource
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Resource
    private OrderStatusLogMapper orderStatusLogMapper;

    public boolean canTransition(Integer currentStatus, OrderStateEvent event) {
        if (currentStatus == null || event == null) {
            return false;
        }
        OrderStatusEnum current;
        try {
            current = OrderStatusEnum.getByStatus(currentStatus);
        } catch (java.util.NoSuchElementException ex) {
            return false; // getByStatus 对未知值抛 Optional.get，这里收敛为“不可流转”
        }
        return current != null
                && TRANSITIONS.getOrDefault(current, Map.of()).containsKey(event);
    }

    public OrderStatusEnum target(Integer currentStatus, OrderStateEvent event) {
        OrderStatusEnum current = OrderStatusEnum.getByStatus(currentStatus);
        if (current == null || event == null) {
            throw new BusinessException("未知订单状态或状态事件");
        }
        OrderStatusEnum target = TRANSITIONS.getOrDefault(current, Map.of()).get(event);
        if (target == null) {
            throw new BusinessException("订单状态不允许执行该操作: " + current.getDesc() + " -> " + event);
        }
        return target;
    }

    public int transition(String orderId, OrderStatusEnum expectedState, OrderStateEvent event) {
        return transition(orderId, Set.of(expectedState), event, null);
    }

    public int transition(String orderId, Collection<OrderStatusEnum> expectedStates, OrderStateEvent event) {
        return transition(orderId, expectedStates, event, null);
    }

    public int transition(String orderId, OrderStatusEnum expectedState,
                          OrderStateEvent event, OrderInfo patch) {
        return transition(orderId, Set.of(expectedState), event, patch);
    }

    public int transition(String orderId, Collection<OrderStatusEnum> expectedStates,
                          OrderStateEvent event, OrderInfo patch) {
        if (StringTools.isEmpty(orderId) || expectedStates == null || expectedStates.isEmpty()) {
            throw new IllegalArgumentException("订单ID和前置状态不能为空");
        }
        OrderStatusEnum target = resolveCommonTarget(expectedStates, event);
        OrderInfo current = orderInfoMapper.selectByOrderId(orderId);
        if (expectedStates.size() == 1 && expectedStates.iterator().next() == target && patch == null) {
            // 幂等重入：期望状态即目标状态时退化为读比对，避免无谓 UPDATE。
            return current != null && target.getStatus().equals(current.getOrderStatus()) ? 1 : 0;
        }
        OrderInfo update = patch == null ? new OrderInfo() : patch;
        update.setOrderStatus(target.getStatus());
        OrderInfoQuery query = new OrderInfoQuery();
        query.setOrderId(orderId);
        applyExpectedStates(query, expectedStates);
        int rows = nullToZero(orderInfoMapper.updateByParam(update, query));
        if (rows > 0) {
            Integer from = current != null ? current.getOrderStatus()
                    : expectedStates.size() == 1 ? expectedStates.iterator().next().getStatus() : null;
            String payOrderId = current != null ? current.getPayOrderId()
                    : patch != null ? patch.getPayOrderId() : null;
            recordLog(orderId, payOrderId, from, target, event, "state-machine");
        }
        return rows;
    }

    public int transitionPayOrder(String payOrderId, OrderStatusEnum expectedState, OrderStateEvent event) {
        if (StringTools.isEmpty(payOrderId)) {
            throw new IllegalArgumentException("支付订单ID不能为空");
        }
        OrderStatusEnum target = target(expectedState.getStatus(), event);
        OrderInfo update = new OrderInfo();
        update.setOrderStatus(target.getStatus());
        OrderInfoQuery query = new OrderInfoQuery();
        query.setPayOrderId(payOrderId);
        query.setOrderStatus(expectedState.getStatus());
        OrderInfoQuery before = new OrderInfoQuery();
        before.setPayOrderId(payOrderId);
        before.setOrderStatus(expectedState.getStatus());
        java.util.List<OrderInfo> beforeList = orderInfoMapper.selectList(before);
        int rows = nullToZero(orderInfoMapper.updateByParam(update, query));
        if (rows > 0 && beforeList != null && rows < beforeList.size()) {
            // 批量 UPDATE 只影响部分子单：同事务回滚（含已写日志），避免把未流转的单写成已流转。
            throw new BusinessException("支付订单状态已变化，请重试");
        }
        if (rows > 0 && beforeList != null) {
            for (OrderInfo order : beforeList) {
                recordLog(order.getOrderId(), payOrderId, expectedState.getStatus(), target, event, "pay-order");
            }
        }
        return rows;
    }

    private void recordLog(String orderId, String payOrderId, Integer from, OrderStatusEnum to,
                           OrderStateEvent event, String remark) {
        if (orderStatusLogMapper == null) {
            return;
        }
        OrderStatusLog log = new OrderStatusLog();
        log.setOrderId(orderId);
        log.setPayOrderId(payOrderId);
        log.setFromStatus(from);
        log.setToStatus(to.getStatus());
        log.setEvent(event.name());
        log.setOperatorType("SYSTEM");
        log.setRemark(remark);
        orderStatusLogMapper.insert(log);
    }

    private OrderStatusEnum resolveCommonTarget(Collection<OrderStatusEnum> expectedStates, OrderStateEvent event) {
        OrderStatusEnum commonTarget = null;
        for (OrderStatusEnum state : expectedStates) {
            if (state == null) {
                throw new BusinessException("未知订单状态或状态事件");
            }
            OrderStatusEnum candidate = target(state.getStatus(), event);
            if (commonTarget != null && commonTarget != candidate) {
                throw new IllegalArgumentException("多个前置状态没有共同目标状态");
            }
            commonTarget = candidate;
        }
        return commonTarget;
    }

    private void applyExpectedStates(OrderInfoQuery query, Collection<OrderStatusEnum> expectedStates) {
        if (expectedStates.size() == 1) {
            query.setOrderStatus(expectedStates.iterator().next().getStatus());
            return;
        }
        query.setOrderStatusList(expectedStates.stream().map(OrderStatusEnum::getStatus).toArray(Integer[]::new));
    }

    private int nullToZero(Integer value) {
        return value == null ? 0 : value;
    }

    private static Map<OrderStatusEnum, Map<OrderStateEvent, OrderStatusEnum>> buildTransitions() {
        Map<OrderStatusEnum, Map<OrderStateEvent, OrderStatusEnum>> transitions =
                new EnumMap<>(OrderStatusEnum.class);
        register(transitions, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAY_SUCCESS, OrderStatusEnum.PAID);
        register(transitions, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.COUPON_RUSH_PAY_SUCCESS,
                OrderStatusEnum.COMPLETED);
        register(transitions, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.USER_CANCEL, OrderStatusEnum.CANCELLED);
        register(transitions, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.SYSTEM_CANCEL, OrderStatusEnum.CLOSED);
        register(transitions, OrderStatusEnum.WAIT_PAYMENT, OrderStateEvent.PAYMENT_TIMEOUT, OrderStatusEnum.CLOSED);
        register(transitions, OrderStatusEnum.PAID, OrderStateEvent.SHIP, OrderStatusEnum.SHIPPED);
        for (OrderStatusEnum refundable : Set.of(
                OrderStatusEnum.PAID, OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED)) {
            register(transitions, refundable, OrderStateEvent.PARTIAL_REFUND,
                    OrderStatusEnum.PARTIALLY_REFUNDED);
            register(transitions, refundable, OrderStateEvent.FULL_REFUND, OrderStatusEnum.REFUNDED);
        }
        for (OrderStatusEnum receivable : Set.of(
                OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED)) {
            register(transitions, receivable, OrderStateEvent.CONFIRM_RECEIPT, OrderStatusEnum.COMPLETED);
        }
        for (OrderStatusEnum removable : Set.of(
                OrderStatusEnum.COMPLETED, OrderStatusEnum.CANCELLED,
                OrderStatusEnum.CLOSED, OrderStatusEnum.REFUNDED)) {
            register(transitions, removable, OrderStateEvent.DELETE, OrderStatusEnum.DELETE);
        }
        return transitions;
    }

    private static void register(Map<OrderStatusEnum, Map<OrderStateEvent, OrderStatusEnum>> transitions,
                                 OrderStatusEnum from, OrderStateEvent event, OrderStatusEnum to) {
        transitions.computeIfAbsent(from, ignored -> new EnumMap<>(OrderStateEvent.class)).put(event, to);
    }
}
