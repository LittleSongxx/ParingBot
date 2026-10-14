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
