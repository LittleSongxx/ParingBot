package com.smartlect.mappers;

import com.smartlect.entity.po.OrderInfo;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

public interface OrderInfoMapper<T,P> extends BaseMapper<T,P> {

	 Integer updateByOrderId(@Param("bean") T t,@Param("orderId") String orderId);

	 Integer deleteByOrderId(@Param("orderId") String orderId);

	 T selectByOrderId(@Param("orderId") String orderId);

	 T selectByOrderIdForUpdate(@Param("orderId") String orderId);

		@Select("""
				SELECT order_id AS orderId, user_id AS userId FROM order_info
				WHERE order_status = 1
				  AND order_time IS NOT NULL
				  AND order_time <= DATE_SUB(NOW(), INTERVAL #{delayHours} HOUR)
				ORDER BY order_time ASC
				LIMIT #{limit}
				""")
		List<OrderInfo> selectDelayedPaidOrders(
				@Param("delayHours") int delayHours,
				@Param("limit") int limit);

		@Select("""
				SELECT o.order_id AS orderId, o.user_id AS userId FROM order_info o
				JOIN (
				    SELECT order_id, MIN(record_time) AS shipped_at
				    FROM order_logistics_info_record
			    GROUP BY order_id
			) shipped ON shipped.order_id = o.order_id
			WHERE o.order_status IN (2, 7)
			  AND shipped.shipped_at <= DATE_SUB(NOW(), INTERVAL #{delayMinutes} MINUTE)
				ORDER BY shipped.shipped_at ASC
				LIMIT #{limit}
				""")
		List<OrderInfo> selectAutoReceivableOrders(
			@Param("delayMinutes") int delayMinutes,
			@Param("limit") int limit);

		// 支付轮询对账（ADR-0018）：只捞"创建超过 N 分钟仍待付款"的单，正常支付中的用户不查渠道；
		// 兜底目标是 MQ 支付事件丢失/进程崩溃后的状态收敛。走 idx_order_status_time 索引。
		@Select("""
				SELECT order_id AS orderId, pay_order_id AS payOrderId, pay_channel AS payChannel
				FROM order_info
				WHERE order_status = 0
				  AND order_time IS NOT NULL
				  AND order_time <= DATE_SUB(NOW(), INTERVAL #{delayMinutes} MINUTE)
				ORDER BY order_time ASC
				LIMIT #{limit}
				""")
		List<OrderInfo> selectWaitPaymentBefore(
			@Param("delayMinutes") int delayMinutes,
			@Param("limit") int limit);

	}
