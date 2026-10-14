package com.smartlect.mappers;

import com.smartlect.entity.po.LocalMessageOutbox;
import org.apache.ibatis.annotations.Param;

import java.util.Date;
import java.util.List;

public interface LocalMessageOutboxMapper {

    Integer insert(LocalMessageOutbox row);

    LocalMessageOutbox selectById(@Param("id") Long id);

    LocalMessageOutbox selectByIdempotencyKey(@Param("idempotencyKey") String idempotencyKey);

    Integer claimForDispatch(@Param("id") Long id,
                             @Param("pendingStatus") Integer pendingStatus,
                             @Param("failedStatus") Integer failedStatus,
                             @Param("sendingStatus") Integer sendingStatus,
                             @Param("leaseOwner") String leaseOwner,
                             @Param("leaseMicros") long leaseMicros);

    Integer markSent(@Param("id") Long id,
                     @Param("sendingStatus") Integer sendingStatus,
                     @Param("sentStatus") Integer sentStatus,
                     @Param("leaseOwner") String leaseOwner,
                     @Param("sentTime") Date sentTime);

    Integer markFailed(@Param("id") Long id,
                       @Param("sendingStatus") Integer sendingStatus,
                       @Param("failedStatus") Integer failedStatus,
                       @Param("leaseOwner") String leaseOwner,
                       @Param("errorMessage") String errorMessage,
                       @Param("backoffSeconds") long backoffSeconds);

    Integer markRetriesExhausted(@Param("failedStatus") Integer failedStatus,
                                 @Param("sendingStatus") Integer sendingStatus,
                                 @Param("exhaustedStatus") Integer exhaustedStatus,
                                 @Param("maxRetries") int maxRetries);

    /**
     * 定时消息驻留：距到期还超过 broker 时间轮上限时把 next_retry_time 推到
     * "到期 - 上限 + 安全余量"（唤醒后剩余延迟已低于上限，投递不再被 40012 拒绝）。
     * 判定与写入全部用数据库时钟；未触发驻留时返回 0（调用方继续正常投递）。
     */
    Integer parkUntilTimerHorizon(@Param("id") Long id,
                                  @Param("pendingStatus") Integer pendingStatus,
                                  @Param("failedStatus") Integer failedStatus,
                                  @Param("horizonMs") long horizonMs,
                                  @Param("wakeBeforeMs") long wakeBeforeMs);

    Integer requeueExhausted(@Param("id") Long id,
                             @Param("exhaustedStatus") Integer exhaustedStatus,
                             @Param("pendingStatus") Integer pendingStatus);

    Integer countByStatus(@Param("status") Integer status);

    List<LocalMessageOutbox> selectByStatus(@Param("status") Integer status,
                                            @Param("limit") int limit);

    List<LocalMessageOutbox> selectDispatchBatch(@Param("pendingStatus") Integer pendingStatus,
                                                 @Param("failedStatus") Integer failedStatus,
                                                 @Param("sendingStatus") Integer sendingStatus,
                                                 @Param("beforeTime") Date beforeTime,
                                                 @Param("maxRetries") int maxRetries,
                                                 @Param("limit") int limit);
}
