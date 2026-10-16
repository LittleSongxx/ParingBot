package com.smartlect.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.smartlect.compensation.StockBatchCompensatePort;
import com.smartlect.utils.JsonUtils;
import com.smartlect.compensation.UserCouponStatusCompensatePort;
import com.smartlect.component.MqCompensationStore;
import com.smartlect.component.MqIdempotencyGuard;
import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.entity.dto.MqCompensationRecord;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.enums.MqCompensationLogStatusEnum;
import com.smartlect.entity.po.MqCompensationLog;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.entity.query.MqCompensationLogQuery;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.MqCompensationLogMapper;
import com.smartlect.service.MqCompensationLogService;
import com.smartlect.support.MqConsumeReplayRouter;
import com.smartlect.utils.PageUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;
import java.util.List;

@Service("mqCompensationLogService")
@Slf4j
public class MqCompensationLogServiceImpl implements MqCompensationLogService {

    @Resource
    private MqCompensationLogMapper<MqCompensationLog, MqCompensationLogQuery> mqCompensationLogMapper;
    @Resource
    private MqIdempotencyGuard mqIdempotencyGuard;
    @Resource
    private MqCompensationStore mqCompensationStore;
    @Lazy
    @Resource
    private ReliableMessageSender reliableMessageSender;
    @Lazy
    @Resource
    private ObjectProvider<StockBatchCompensatePort> stockBatchCompensatePort;
    @Lazy
    @Resource
    private ObjectProvider<UserCouponStatusCompensatePort> userCouponStatusCompensatePort;

    @Override
    public PaginationResultVO<MqCompensationLog> findListByPage(MqCompensationLogQuery param) {
        return PageUtils.page(param.getPageNo(), param.getPageSize(), () -> mqCompensationLogMapper.selectList(param));
    }

    @Override
    public MqCompensationLog getByLogId(Integer logId) {
        return mqCompensationLogMapper.selectByLogId(logId);
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRES_NEW, rollbackFor = Exception.class)
    public void saveFromFailure(MqCompensationRecord record) {
        if (record == null || StringTools.isEmpty(record.getIdempotencyKey())) {
            return;
        }
        Date now = new Date();
        MqCompensationLog existing = mqCompensationLogMapper.selectByIdempotencyKey(record.getIdempotencyKey());
        if (existing != null) {
            MqCompensationLog patch = new MqCompensationLog();
            patch.setErrorMessage(record.getErrorMessage());
            patch.setRetryCount((existing.getRetryCount() == null ? 0 : existing.getRetryCount()));
            patch.setStatus(MqCompensationLogStatusEnum.PENDING.getStatus());
            patch.setUpdateTime(now);
            mqCompensationLogMapper.updateByLogId(patch, existing.getLogId());
            return;
        }
        MqCompensationLog logRow = new MqCompensationLog();
        logRow.setIdempotencyKey(record.getIdempotencyKey());
        logRow.setExchange(record.getExchange());
        logRow.setRoutingKey(record.getRoutingKey());
        logRow.setBizScene(resolveBizScene(record));
        logRow.setPayloadJson(JsonUtils.toJson(record.getPayload()));
        logRow.setReliabilityLevel(record.getReliabilityLevel() == null
                ? MessageReliabilityLevelEnum.HIGH.getCode()
                : record.getReliabilityLevel().getCode());
        logRow.setErrorMessage(record.getErrorMessage());
        logRow.setRetryCount(record.getRetryCount());
        logRow.setStatus(MqCompensationLogStatusEnum.PENDING.getStatus());
        logRow.setCreateTime(now);
        logRow.setUpdateTime(now);
        mqCompensationLogMapper.insert(logRow);
    }

    @Override
    public void updateHandleStatus(Integer logId, Integer status, String handleRemark) {
        MqCompensationLog existing = mqCompensationLogMapper.selectByLogId(logId);
        if (existing == null) {
            throw new BusinessException("补偿日志不存在");
        }
        MqCompensationLogStatusEnum statusEnum = MqCompensationLogStatusEnum.getByStatus(status);
        if (statusEnum == null) {
            throw new BusinessException("无效的处理状态");
        }
        Date now = new Date();
        MqCompensationLog patch = new MqCompensationLog();
        patch.setStatus(status);
        patch.setHandleRemark(handleRemark);
        patch.setHandleTime(now);
        patch.setUpdateTime(now);
        mqCompensationLogMapper.updateByLogId(patch, logId);
    }

    @Override
    public void replay(Integer logId) {
        MqCompensationLog existing = mqCompensationLogMapper.selectByLogId(logId);
        if (existing == null) {
            throw new BusinessException("补偿日志不存在");
        }
        if (MqCompensationLogStatusEnum.REPLAYED.getStatus().equals(existing.getStatus())
                || MqCompensationLogStatusEnum.IGNORED.getStatus().equals(existing.getStatus())) {
            throw new BusinessException("当前状态不可重放");
        }
        if (InternalApiHeaders.REMOTE_COMPENSATE_EXCHANGE.equals(existing.getExchange())) {
            replayRemoteCompensate(existing);
            return;
        }
        if (MqConsumeReplayRouter.isConsumeFailure(existing.getExchange())) {
            replayConsumeFailure(existing);
            return;
        }
        replaySendFailure(existing);
    }

    @Override
    public int autoReplayPendingSendFailures(int batchSize, int maxRetryCount) {
        if (batchSize <= 0) {
            batchSize = 10;
        }
        MqCompensationLogQuery query = new MqCompensationLogQuery();
        query.setStatus(MqCompensationLogStatusEnum.PENDING.getStatus());
        query.setOrderBy(com.smartlect.entity.query.SafeSort.of("log_id asc"));
        List<MqCompensationLog> list = PageUtils.pageInfo(1, batchSize * 2,
                () -> mqCompensationLogMapper.selectList(query)).getList();
        if (list == null || list.isEmpty()) {
            return 0;
        }
        int replayed = 0;
        for (MqCompensationLog row : list) {
            if (replayed >= batchSize) {
                break;
            }
            if (MqConsumeReplayRouter.isConsumeFailure(row.getExchange())) {
                continue;
            }
            int retry = row.getRetryCount() == null ? 0 : row.getRetryCount();
            if (retry >= maxRetryCount) {
                continue;
            }
            try {
                if (InternalApiHeaders.REMOTE_COMPENSATE_EXCHANGE.equals(row.getExchange())) {
                    replayRemoteCompensate(row);
                } else {
                    replaySendFailure(row);
                }
                replayed++;
            } catch (Exception e) {
                log.warn("MQ 自动补偿重放失败 logId={}", row.getLogId(), e);
            }
        }
        return replayed;
    }

    private void replayRemoteCompensate(MqCompensationLog existing) {
        Date now = new Date();
        markProcessing(existing.getLogId(), now);
        try {
            String routingKey = existing.getRoutingKey();
            if (InternalApiHeaders.REMOTE_STOCK_CHANGE_BATCH.equals(routingKey)) {
                List<ProductItem> items = JsonUtils.parseArray(existing.getPayloadJson(), ProductItem.class);
                StockBatchCompensatePort stockPort = stockBatchCompensatePort.getIfAvailable();
                if (stockPort == null) {
                    throw new BusinessException("库存补偿能力不可用（缺少 stock-api）");
                }
                // 用补偿行自身的幂等键当业务键：同一行重复重放被库存侧幂等挡掉，
                // 不会重复加库存（此前传 null 键 → 每次重放都真的 apply，2026-10-16 审计）
                stockPort.changeStockBatch(items, "compensation:" + existing.getIdempotencyKey());
            } else if (InternalApiHeaders.REMOTE_STOCK_ORDER_RESTORE.equals(routingKey)) {
                JsonNode payload = JsonUtils.parseTree(existing.getPayloadJson());
                StockBatchCompensatePort stockPort = stockBatchCompensatePort.getIfAvailable();
                if (stockPort == null) {
                    throw new BusinessException("库存补偿能力不可用（缺少 stock-api）");
                }
                JsonNode itemsNode = payload == null ? null : payload.get("items");
                List<ProductItem> items = itemsNode == null
                        ? List.of()
                        : JsonUtils.parseArray(itemsNode.toString(), ProductItem.class);
                stockPort.restoreOrderStock(textOrNull(payload, "payOrderId"), items);
            } else if (InternalApiHeaders.REMOTE_COUPON_UNLOCK.equals(routingKey)) {
                JsonNode payload = JsonUtils.parseTree(existing.getPayloadJson());
                UserCouponStatusCompensatePort couponPort = userCouponStatusCompensatePort.getIfAvailable();
                if (couponPort == null) {
                    throw new BusinessException("优惠券补偿能力不可用（缺少 coupon-api）");
                }
                couponPort.changeUserCouponStatus(
                        textOrNull(payload, "userCouponId"),
                        textOrNull(payload, "userId"),
                        intOrNull(payload, "fromStatus"),
                        intOrNull(payload, "toStatus"),
                        null);
            } else {
                throw new BusinessException("未知远程补偿类型：" + routingKey);
            }
            markReplayed(existing, now);
            mqCompensationStore.remove(existing.getIdempotencyKey());
        } catch (Exception e) {
            log.error("远程补偿重放失败 logId={}", existing.getLogId(), e);
            markReplayFailed(existing, e.getMessage());
            throw new BusinessException("远程补偿重放失败：" + e.getMessage());
        }
    }

    private void replaySendFailure(MqCompensationLog existing) {
        Date now = new Date();
        markProcessing(existing.getLogId(), now);
        mqIdempotencyGuard.releaseSend(existing.getIdempotencyKey());
        try {
            Object payload = JsonUtils.parse(existing.getPayloadJson());
            reliableMessageSender.replaySend(
                    existing.getExchange(),
                    existing.getRoutingKey(),
                    payload,
                    existing.getIdempotencyKey());
            markReplayed(existing, now);
            mqCompensationStore.remove(existing.getIdempotencyKey());
        } catch (Exception e) {
            log.error("MQ 补偿重放失败 logId={}", existing.getLogId(), e);
            markReplayFailed(existing, e.getMessage());
            throw new BusinessException("重放失败：" + e.getMessage());
        }
    }

    private void replayConsumeFailure(MqCompensationLog existing) {
        MqConsumeReplayRouter.Target target = MqConsumeReplayRouter.resolve(existing.getRoutingKey());
        if (target == null) {
            throw new BusinessException("未知消费队列，无法重放：" + existing.getRoutingKey());
        }
        Date now = new Date();
        markProcessing(existing.getLogId(), now);
        mqIdempotencyGuard.releaseSend(existing.getIdempotencyKey());
        try {
            Object payload = JsonUtils.parse(existing.getPayloadJson());
            reliableMessageSender.replaySend(
                    target.exchange(),
                    target.routingKey(),
                    payload,
                    existing.getIdempotencyKey());
            markReplayed(existing, now);
            mqCompensationStore.remove(existing.getIdempotencyKey());
        } catch (Exception e) {
            log.error("MQ 消费补偿重放失败 logId={}", existing.getLogId(), e);
            markReplayFailed(existing, e.getMessage());
            throw new BusinessException("重放失败：" + e.getMessage());
        }
    }

    private void markProcessing(Integer logId, Date now) {
        MqCompensationLog processing = new MqCompensationLog();
        processing.setStatus(MqCompensationLogStatusEnum.PROCESSING.getStatus());
        processing.setUpdateTime(now);
        mqCompensationLogMapper.updateByLogId(processing, logId);
    }

    private void markReplayed(MqCompensationLog existing, Date now) {
        MqCompensationLog success = new MqCompensationLog();
        success.setStatus(MqCompensationLogStatusEnum.REPLAYED.getStatus());
        success.setRetryCount((existing.getRetryCount() == null ? 0 : existing.getRetryCount()) + 1);
        success.setHandleTime(now);
        success.setUpdateTime(now);
        mqCompensationLogMapper.updateByLogId(success, existing.getLogId());
    }

    private void markReplayFailed(MqCompensationLog existing, String errorMessage) {
        MqCompensationLog failed = new MqCompensationLog();
        failed.setStatus(MqCompensationLogStatusEnum.REPLAY_FAILED.getStatus());
        failed.setRetryCount((existing.getRetryCount() == null ? 0 : existing.getRetryCount()) + 1);
        failed.setErrorMessage(errorMessage);
        failed.setUpdateTime(new Date());
        mqCompensationLogMapper.updateByLogId(failed, existing.getLogId());
    }

    static String resolveBizScene(MqCompensationRecord record) {
        if (InternalApiHeaders.REMOTE_COMPENSATE_EXCHANGE.equals(record.getExchange())) {
            return "REMOTE_" + resolveBizScene(record.getRoutingKey());
        }
        if (MqConsumeReplayRouter.isConsumeFailure(record.getExchange())) {
            return "CONSUME_" + resolveBizScene(record.getRoutingKey());
        }
        return resolveBizScene(record.getRoutingKey());
    }

    static String resolveBizScene(String routingKey) {
        if (StringTools.isEmpty(routingKey)) {
            return "OTHER";
        }
        String key = routingKey.toLowerCase();
        if (key.contains("stock")) {
            return "STOCK";
        }
        if (key.contains("coupon")) {
            return "COUPON";
        }
        if (key.contains("smartlect.notify")) {
            return "NOTIFY";
        }
        if (key.contains("browse")) {
            return "BROWSE";
        }
        if (key.contains("sign")) {
            return "SIGN";
        }
        if (key.contains("pay") || key.contains("timeout") || key.contains("logistics") || key.contains("confirm")) {
            return "PAY";
        }
        if (key.contains("ban")) {
            return "BAN";
        }
        return "OTHER";
    }

    private static String textOrNull(JsonNode node, String field) {
        if (node == null || !node.has(field) || node.get(field).isNull()) {
            return null;
        }
        return node.get(field).asText();
    }

    private static Integer intOrNull(JsonNode node, String field) {
        if (node == null || !node.has(field) || node.get(field).isNull()) {
            return null;
        }
        return node.get(field).asInt();
    }
}
