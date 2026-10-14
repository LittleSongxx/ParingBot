package com.smartlect.biz.impl;

import com.smartlect.api.enums.OrderFromTypeEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.mappers.OrderInfoMapper;

import java.util.List;

/**
 * 订单状态判定与按支付单装载的共享事实工具（批次二拆分 OrderInfoServiceImpl 时抽出，
 * 供创建/支付/取消三个领域服务与门面共用，避免判定逻辑三处漂移）。
 */
final class OrderFacts {

    private OrderFacts() {
    }

    static boolean isCouponRushOrder(OrderInfo orderInfo) {
        if (orderInfo == null || orderInfo.getPayScene() == null) {
            return false;
        }
        return String.valueOf(OrderFromTypeEnum.COUPON.getType()).equals(orderInfo.getPayScene());
    }

    static boolean isPaidOrBeyond(Integer status) {
        if (status == null) {
            return false;
        }
        return OrderStatusEnum.PAID.getStatus().equals(status)
                || OrderStatusEnum.SHIPPED.getStatus().equals(status)
                || OrderStatusEnum.COMPLETED.getStatus().equals(status)
                || OrderStatusEnum.REFUNDED.getStatus().equals(status)
                || OrderStatusEnum.PARTIALLY_REFUNDED.getStatus().equals(status);
    }

    static boolean isClosedOrCancelled(Integer status) {
        return OrderStatusEnum.CLOSED.getStatus().equals(status)
                || OrderStatusEnum.CANCELLED.getStatus().equals(status);
    }

    static List<OrderInfo> loadOrdersByPayOrderId(
            OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper, String payOrderId) {
        OrderInfoQuery query = new OrderInfoQuery();
        query.setPayOrderId(payOrderId);
        return orderInfoMapper.selectList(query);
    }
}
