package com.smartlect.mappers;

import com.smartlect.entity.po.OrderRequestIdempotency;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

public interface OrderRequestIdempotencyMapper {

    @Insert("""
            insert into order_request_idempotency
                (user_id, command_type, idempotency_key, request_hash, status, create_time, update_time)
            values
                (#{userId}, #{commandType}, #{idempotencyKey}, #{requestHash},
                 'PROCESSING', current_timestamp, current_timestamp)
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertProcessing(OrderRequestIdempotency record);

    @Select("""
            select id, user_id, command_type, idempotency_key, request_hash,
                   status, response_json, reconcile_attempts, reconcile_deadline,
                   last_reconcile_at, review_reason, create_time, update_time
            from order_request_idempotency
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
            for update
            """)
    OrderRequestIdempotency selectForUpdate(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey);

    @Select("""
            select id, user_id, command_type, idempotency_key, request_hash,
                   status, response_json, reconcile_attempts, reconcile_deadline,
                   last_reconcile_at, review_reason, create_time, update_time
            from order_request_idempotency
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
            """)
    OrderRequestIdempotency select(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey);

    @Update("""
            update order_request_idempotency
            set status = 'COMPLETED',
                response_json = #{responseJson},
                update_time = current_timestamp
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
              and status = 'PROCESSING'
            """)
    int markCompleted(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey,
            @Param("responseJson") String responseJson);

    @Update("""
            update order_request_idempotency
            set status = 'FAILED',
                response_json = #{responseJson},
                update_time = current_timestamp
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
              and status = 'PROCESSING'
            """)
    int markFailed(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey,
            @Param("responseJson") String responseJson);

    @Update("""
            update order_request_idempotency
            set status = 'COMPLETED',
                response_json = #{responseJson},
                update_time = current_timestamp
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
              and status in ('PROCESSING', 'FAILED', 'INCONCLUSIVE', 'MANUAL_REVIEW')
            """)
    int markReconciled(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey,
            @Param("responseJson") String responseJson);

    @Update("""
            update order_request_idempotency
            set status = case
                    when reconcile_attempts + 1 >= #{maxAttempts}
                      or coalesce(reconcile_deadline, #{reconcileDeadline}) <= current_timestamp
                    then 'MANUAL_REVIEW' else 'INCONCLUSIVE' end,
                reconcile_attempts = reconcile_attempts + 1,
                reconcile_deadline = coalesce(reconcile_deadline, #{reconcileDeadline}),
                last_reconcile_at = current_timestamp,
                review_reason = #{reviewReason},
                update_time = current_timestamp
            where user_id = #{userId}
              and command_type = #{commandType}
              and idempotency_key = #{idempotencyKey}
              and status in ('PROCESSING', 'INCONCLUSIVE')
            """)
    int recordInconclusive(
            @Param("userId") String userId,
            @Param("commandType") String commandType,
            @Param("idempotencyKey") String idempotencyKey,
            @Param("maxAttempts") int maxAttempts,
            @Param("reconcileDeadline") Date reconcileDeadline,
            @Param("reviewReason") String reviewReason);

    /**
     * 待核对行扫描：INCONCLUSIVE / MANUAL_REVIEW 且核对期限已到（或从未设过）。
     * 只读；用于对账哨兵任务（不自动改判，理由见 OrderIdempotencyReconcileTask 注释）。
     */
    @Select("""
            SELECT * FROM order_request_idempotency
            WHERE status IN ('INCONCLUSIVE', 'MANUAL_REVIEW')
              AND (reconcile_deadline IS NULL OR reconcile_deadline <= NOW())
            ORDER BY update_time ASC
            LIMIT #{limit}
            """)
    List<OrderRequestIdempotency> selectStuckForReview(@Param("limit") int limit);
}
