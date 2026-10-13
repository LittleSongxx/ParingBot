package com.smartlect.component;

import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.api.enums.LogisticsStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.constants.Constants;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.po.OrderLogisticsInfoRecord;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.entity.query.OrderLogisticsInfoRecordQuery;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderLogisticsInfoRecordService;
import com.smartlect.biz.OrderLogisticsInfoService;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.mq.MqSubscription;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMessageListener;
import com.smartlect.mq.SmartlectMqMessage;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.Objects;
import java.util.Random;

/**
 * 模拟物流推进：每步 1 小时定时消息链式投递（step+1），到达最大站点数置为已签收
 * 并补发 7 天自动确认收货的定时消息。步骤幂等：record 数已超前则跳过并续排下一步。
 */
@Slf4j
@Component
public class LogisticsStepListener implements SmartlectMessageListener<PayOrderMessageDTO> {

    private static final String[] RECORD_ADDRESSES = {
            "上海市浦东新区中转站", "杭州市萧山区转运中心", "南京市江宁区中转场",
            "无锡市滨湖区分拨中心", "苏州市工业园区集散站", "合肥市蜀山区转运场",
            "武汉市东西湖区中转站", "郑州市郑东新区分拨中心", "济南市历下区转运站",
            "天津市滨海新区中转场", "北京市大兴区集散中心", "广州市白云区转运站",
            "深圳市宝安区中转场", "成都市双流区分拨站", "重庆市渝北区转运中心",
            "西安市未央区集散场", "福州市仓山区中转站", "青岛市崂山区分拨中心",
            "大连市甘井子区转运站", "沈阳市铁西区集散场", "长沙市岳麓区中转站",
            "南昌市东湖区转运中心", "昆明市官渡区分拨站", "贵阳市观山湖区集散场",
            "太原市小店区中转站", "石家庄市长安区转运中心", "哈尔滨市南岗区分拨场",
            "长春市朝阳区集散站", "兰州市城关区中转场", "呼和浩特市新城区转运站"
    };

    @Lazy
    @Resource
    private LogisticsStepListener self;

    @Resource
    private OrderInfoService orderInfoService;
    @Resource
    private OrderStateMachine orderStateMachine;
    @Resource
    private OrderLogisticsInfoService orderLogisticsInfoService;
    @Resource
    private OrderLogisticsInfoRecordService orderLogisticsInfoRecordService;
    @Resource
    private TransactionalMqSender transactionalMqSender;
    @Resource
    private AppConfig appConfig;

    @Override
    public MqSubscription subscription() {
        return MqSubscription.of(RocketMqTopics.TOPIC_DELAY, RocketMqTopics.TAG_LOGISTICS_STEP,
                "G_smartlect_logistics_step");
    }

    @Override
    public Class<PayOrderMessageDTO> payloadType() {
        return PayOrderMessageDTO.class;
    }

    @Override
    public void onMessage(PayOrderMessageDTO message, SmartlectMqMessage mqMessage) {
        if (message == null || StringTools.isEmpty(message.getOrderId())) {
            log.error("模拟物流消息订单为空");
            return;
        }
        log.info("模拟物流消息收到订单: {}, step={}", message.getOrderId(), message.getLogisticsStep());
        self.processOrderLogistics(message);
    }

    @Transactional(rollbackFor = Exception.class)
    public void processOrderLogistics(PayOrderMessageDTO message) {
        final boolean[] sendConfirm = {false};
        final Integer[] nextLogisticsStep = {null};
        try {
            int step = message.getLogisticsStep() == null ? 0 : message.getLogisticsStep();
            String orderId = message.getOrderId();
            OrderInfo orderInfo = orderInfoService.getOrderInfoByOrderId(orderId);
            if (orderInfo == null) {
                return;
            }
            OrderLogisticsInfo orderLogisticsInfo =
                    orderLogisticsInfoService.getOrderLogisticsInfoByOrderId(orderId);
            if (orderLogisticsInfo == null) {
                log.warn("物流信息不存在，orderId: {}", orderId);
                return;
            }

            OrderLogisticsInfoRecordQuery recordQuery = new OrderLogisticsInfoRecordQuery();
            recordQuery.setOrderId(orderId);
            Integer recordCount = orderLogisticsInfoRecordService.findCountByParam(recordQuery);
            int count = recordCount == null ? 0 : recordCount;
            if (count > step) {
                log.info("物流步骤幂等跳过 orderId={}, step={}, recordCount={}",
                        orderId, step, count);
                scheduleNextIfNeeded(
                        orderInfo, orderLogisticsInfo, count, sendConfirm, nextLogisticsStep);
                return;
            }
            if (count < step) {
                log.warn("物流步骤乱序 orderId={}, step={}, recordCount={}",
                        orderId, step, count);
                return;
            }

            OrderLogisticsInfoRecord orderLogisticsInfoRecord = new OrderLogisticsInfoRecord();
            orderLogisticsInfoRecord.setOrderId(orderId);
            orderLogisticsInfoRecord.setRecordTime(StringTools.getCurrentDate());

            if (step == 0) {
                if (!Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.PAID.getStatus())) {
                    if (Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.SHIPPED.getStatus())
                            || Objects.equals(
                                    orderInfo.getOrderStatus(),
                                    OrderStatusEnum.PARTIALLY_REFUNDED.getStatus())
                            || Objects.equals(
                                    orderInfo.getOrderStatus(),
                                    OrderStatusEnum.COMPLETED.getStatus())) {
                        scheduleNextIfNeeded(
                                orderInfo, orderLogisticsInfo, count, sendConfirm, nextLogisticsStep);
                    }
                    return;
                }
                orderLogisticsInfoRecord.setRecordAddress(orderLogisticsInfo.getSenderAddress());
                orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.IN_TRANSIT.getStatus());
                orderLogisticsInfo.setLogisticsCompany("顺丰");
                orderLogisticsInfo.setLogisticsNo(
                        "SF" + StringTools.getRandomNumber(Constants.LENGTH_30));
                // 状态机 CAS：PAID→SHIPPED。0 行说明并发下已被发货（如管理员手工发货），
                // 保持旧逻辑的推进语义：不报错、不重复写状态，继续后续物流推进。
                if (orderStateMachine.transition(orderId, OrderStatusEnum.PAID, OrderStateEvent.SHIP) == 0) {
                    log.info("模拟物流发货被并发抢先 orderId={}，按已发货继续推进", orderId);
                }
                OrderLogisticsInfoQuery logisticsQuery = new OrderLogisticsInfoQuery();
                logisticsQuery.setOrderId(orderId);
                orderLogisticsInfoService.updateByParam(orderLogisticsInfo, logisticsQuery);
                sendConfirm[0] = true;
            } else if (Objects.equals(
                            orderInfo.getOrderStatus(), OrderStatusEnum.SHIPPED.getStatus())
                    || Objects.equals(
                            orderInfo.getOrderStatus(),
                            OrderStatusEnum.PARTIALLY_REFUNDED.getStatus())
                    || Objects.equals(
                            orderInfo.getOrderStatus(), OrderStatusEnum.COMPLETED.getStatus())) {
                orderLogisticsInfoRecord.setRecordAddress(
                        RECORD_ADDRESSES[new Random().nextInt(RECORD_ADDRESSES.length)]);
            } else {
                return;
            }

            int maxStations = appConfig.getLogisticsSimulateMaxStations();
            int countAfter = count + 1;
            if (countAfter >= maxStations) {
                orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.DELIVERED.getStatus());
                orderLogisticsInfoRecord.setRecordAddress(orderLogisticsInfo.getReceiverAddress());
            } else {
                nextLogisticsStep[0] = step + 1;
            }

            OrderLogisticsInfoQuery updateQuery = new OrderLogisticsInfoQuery();
            updateQuery.setOrderId(orderId);
            orderLogisticsInfoService.updateByParam(orderLogisticsInfo, updateQuery);
            orderLogisticsInfoRecordService.add(orderLogisticsInfoRecord);
        } finally {
            queueLogisticsFollowUps(message.getOrderId(), sendConfirm[0], nextLogisticsStep[0]);
        }
    }

    private void queueLogisticsFollowUps(
            String orderId, boolean sendConfirm, Integer nextLogisticsStep) {
        long now = System.currentTimeMillis();
        if (sendConfirm) {
            PayOrderMessageDTO confirmDto = new PayOrderMessageDTO(orderId);
            transactionalMqSender.sendAfterCommit(
                    RocketMqTopics.TOPIC_DELAY,
                    RocketMqTopics.TAG_CONFIRM_RECEIPT,
                    confirmDto,
                    MqIdempotencyKeys.payConfirm(orderId),
                    MessageReliabilityLevelEnum.STANDARD,
                    now + RocketMqTopics.CONFIRM_RECEIPT.toMillis());
        }
        if (nextLogisticsStep != null) {
            PayOrderMessageDTO nextDto = new PayOrderMessageDTO(orderId);
            nextDto.setLogisticsStep(nextLogisticsStep);
            transactionalMqSender.sendAfterCommit(
                    RocketMqTopics.TOPIC_DELAY,
                    RocketMqTopics.TAG_LOGISTICS_STEP,
                    nextDto,
                    MqIdempotencyKeys.payLogistics(orderId, nextLogisticsStep),
                    MessageReliabilityLevelEnum.STANDARD,
                    now + RocketMqTopics.LOGISTICS_STEP.toMillis());
        }
    }

    private void scheduleNextIfNeeded(OrderInfo orderInfo, OrderLogisticsInfo orderLogisticsInfo, int recordCount,
                                      boolean[] sendConfirm, Integer[] nextLogisticsStep) {
        if (Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.PAID.getStatus())) {
            return;
        }
        int maxStations = appConfig.getLogisticsSimulateMaxStations();
        if (recordCount == 0) {
            return;
        }
        if (recordCount == 1 && Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.SHIPPED.getStatus())) {
            sendConfirm[0] = true;
        }
        if (recordCount < maxStations
                && !Objects.equals(orderLogisticsInfo.getLogisticsStatus(), LogisticsStatusEnum.DELIVERED.getStatus())) {
            nextLogisticsStep[0] = recordCount;
        }
    }
}
