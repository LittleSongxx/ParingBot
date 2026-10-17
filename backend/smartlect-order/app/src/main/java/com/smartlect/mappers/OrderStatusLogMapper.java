package com.smartlect.mappers;

import com.smartlect.entity.po.OrderStatusLog;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 订单状态历史：只追加、只读，不提供 update/delete。 */
public interface OrderStatusLogMapper {

    @Insert("""
            insert into order_status_log
                (order_id, pay_order_id, from_status, to_status, event,
                 operator_type, operator_id, request_id, remark, create_time)
            values
                (#{orderId}, #{payOrderId}, #{fromStatus}, #{toStatus}, #{event},
                 #{operatorType}, #{operatorId}, #{requestId}, #{remark}, now(3))
            """)
    int insert(OrderStatusLog log);

    @Select("""
            select log_id as logId, order_id as orderId, pay_order_id as payOrderId,
                   from_status as fromStatus, to_status as toStatus, event,
                   operator_type as operatorType, operator_id as operatorId,
                   request_id as requestId, remark, create_time as createTime
            from order_status_log
            where order_id = #{orderId}
            order by log_id asc
            """)
    List<OrderStatusLog> selectByOrderId(@Param("orderId") String orderId);
}
