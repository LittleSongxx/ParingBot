package com.smartlect.service;

import com.smartlect.entity.dto.MqCompensationRecord;
import com.smartlect.entity.po.MqCompensationLog;
import com.smartlect.entity.query.MqCompensationLogQuery;
import com.smartlect.entity.vo.PaginationResultVO;

public interface MqCompensationLogService {

    PaginationResultVO<MqCompensationLog> findListByPage(MqCompensationLogQuery query);

    MqCompensationLog getByLogId(Integer logId);

    void saveFromFailure(MqCompensationRecord record);

    void updateHandleStatus(Integer logId, Integer status, String handleRemark);

    void replay(Integer logId);

    int autoReplayPendingSendFailures(int batchSize, int maxRetryCount);

    /**
     * @param includeConsumeFailures 是否连 `exchange=mq.consume` 的消费失败一起重放。
     *        默认关闭：多数域的消费失败需要人判；coupon 的退款还券是幂等动作，
     *        由 `mq.compensation.auto-replay-consume=true` 单独打开。
     */
    int autoReplayPendingSendFailures(int batchSize, int maxRetryCount, boolean includeConsumeFailures);
}
