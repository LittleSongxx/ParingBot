package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.support.CouponRpcSupport;
import com.smartlect.api.support.PayRpcSupport;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.biz.OrderRequestIdempotencyService;
import com.smartlect.component.CouponRushRedisComponent;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.po.OrderCouponRel;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderCouponRelQuery;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;


import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批次二秒杀流程统一（ADR-0019）的结构性锚定：
 * 1) RUSH_TIMEOUT 关单消息必须写入建单短事务回调内（与订单同事务落库）；
 * 2) 创建占位券（远程）在事务外，失败补偿释放预占、订单交由超时关单收敛；
 * 3) 秒杀支付链路全部远程调用不占用本地事务。
 */
@ExtendWith(MockitoExtension.class)
class CouponRushOrderCreationTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    @Mock
    private OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;
    @Mock
    private CouponRpcSupport couponRpcSupport;
    @Mock
    private PayRpcSupport payRpcSupport;
    @Mock
    private CouponRushRedisComponent couponRushRedisComponent;
    @Mock
    private AppConfig appConfig;
    @Mock
    private TransactionalMqSender transactionalMqSender;
    @Mock
    private OrderRequestIdempotencyService orderRequestIdempotencyService;
    @Mock
    private TransactionTemplate transactionTemplate;

    private CouponRushOrderServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new CouponRushOrderServiceImpl();
        ReflectionTestUtils.setField(service, "orderInfoMapper", orderInfoMapper);
        ReflectionTestUtils.setField(service, "orderItemMapper", orderItemMapper);
        ReflectionTestUtils.setField(service, "orderCouponRelMapper", orderCouponRelMapper);
        ReflectionTestUtils.setField(service, "couponRpcSupport", couponRpcSupport);
        ReflectionTestUtils.setField(service, "payRpcSupport", payRpcSupport);
        ReflectionTestUtils.setField(service, "couponRushRedisComponent", couponRushRedisComponent);
        ReflectionTestUtils.setField(service, "appConfig", appConfig);
        ReflectionTestUtils.setField(service, "transactionalMqSender", transactionalMqSender);
        ReflectionTestUtils.setField(service, "orderRequestIdempotencyService", orderRequestIdempotencyService);
        ReflectionTestUtils.setField(service, "transactionTemplate", transactionTemplate);
        lenient().when(appConfig.getOrderExpireMinute()).thenReturn(15);
    }

    @Test
    void rushTimeoutMessageIsWrittenInsideCreationTransactionAndCouponCreatedAfter() {
        stubPrepareRemoteCalls();
        // 短事务回调：通过调用前后对比 invocations 计数锚定——关单消息在回调内产生（+1），
        // 占位券（远程）不在回调内（计数不变，属事务外 Phase 4）。
        doAnswer(call -> {
            TransactionCallback<?> callback = call.getArgument(0);
            int messagesBefore = org.mockito.Mockito.mockingDetails(transactionalMqSender).getInvocations().size();
            int couponsBefore = org.mockito.Mockito.mockingDetails(couponRpcSupport).getInvocations().size();
            Object result = callback.doInTransaction(null);
            org.junit.jupiter.api.Assertions.assertEquals(messagesBefore + 1,
                    org.mockito.Mockito.mockingDetails(transactionalMqSender).getInvocations().size(),
                    "RUSH_TIMEOUT 关单消息必须在建单短事务回调内写出");
            org.junit.jupiter.api.Assertions.assertEquals(couponsBefore,
                    org.mockito.Mockito.mockingDetails(couponRpcSupport).getInvocations().size(),
                    "创建占位券是远程调用，不得进入短事务回调");
            return result;
        }).when(transactionTemplate).execute(any());

        service.prepareCouponRush("user-1", "c1", "rush-key-000000001");

        // 占位券在建单事务之后创建（无券关系时 useCoupon 路径不触发其它 coupon 调用）
        var sequence = inOrder(transactionTemplate, couponRpcSupport);
        sequence.verify(transactionTemplate).execute(any());
        sequence.verify(couponRpcSupport).createUserCoupon(any(UserCouponCreateDTO.class));
        verify(couponRpcSupport, org.mockito.Mockito.never()).releaseRushCouponReserve(anyString(), anyString());
    }

    @Test
    void placeholderCouponFailureCompensatesReserveAndLeavesOrderToTimeoutClose() {
        stubPrepareRemoteCalls();
        doAnswer(call -> {
            TransactionCallback<?> callback = call.getArgument(0);
            return callback.doInTransaction(null);
        }).when(transactionTemplate).execute(any());
        doThrow(new BusinessException("券服务不可用")).when(couponRpcSupport).createUserCoupon(any());

        assertThrows(BusinessException.class,
                () -> service.prepareCouponRush("user-1", "c1", "rush-key-000000002"));

        // 订单与关单消息已随短事务落库（交由 15 分钟超时关单收敛），这里同步补偿释放预占
        verify(orderInfoMapper).insert(any(OrderInfo.class));
        verify(transactionalMqSender).sendAfterCommit(
                eq(com.smartlect.mq.RocketMqTopics.TOPIC_DELAY),
                eq(com.smartlect.mq.RocketMqTopics.TAG_RUSH_TIMEOUT),
                any(com.smartlect.api.dto.RushingCouponMessageDTO.class),
                anyString(), any(), any());
        verify(couponRpcSupport).releaseRushCouponReserve("c1", "user-1");
    }

    private void stubPrepareRemoteCalls() {
        DiscountCouponVO coupon = new DiscountCouponVO();
        coupon.setCouponId("c1");
        coupon.setCouponName("五元券");
        coupon.setRushingstatus(com.smartlect.api.enums.RushingCouponStatusEnum.YES.getStatus());
        coupon.setRemainCount(100);
        when(couponRpcSupport.getCoupon("c1")).thenReturn(coupon);
        lenient().when(couponRpcSupport.hasAvailableRushStock("c1")).thenReturn(true);
        lenient().when(couponRpcSupport.deductStock("c1", "user-1")).thenReturn(1);
        when(couponRushRedisComponent.rushingCoupon(eq("c1"), eq("user-1"), anyString())).thenReturn(0);
        when(orderRequestIdempotencyService.execute(
                eq("user-1"),
                eq(OrderRequestIdempotencyService.COMMAND_COUPON_RUSH_PREPARE),
                anyString(), any(), eq(com.smartlect.api.dto.CouponRushPrepareDTO.class), any()))
                .thenAnswer(call -> {
                    java.util.function.Supplier<?> command = call.getArgument(5);
                    return command.get();
                });
        // insertCouponRushOrder 依赖：mapper 插入（mock 默认即可）
        lenient().when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);
        lenient().when(orderCouponRelMapper.insert(any(OrderCouponRel.class))).thenReturn(1);
        lenient().when(orderInfoMapper.insert(any(OrderInfo.class))).thenReturn(1);
        lenient().when(orderCouponRelMapper.selectList(any())).thenReturn(List.of());
    }

    @Test
    void rushTimeoutPayloadCarriesCouponIdentityForRollbackBranches() {
        // 2026-10-16 审计 L10：此前发的是只填 orderId 的 PayOrderMessageDTO，消费端按
        // RushingCouponMessageDTO 读到的 userId/couponId/userCouponId 全为 null，
        // "未建单/建单未落库/券存在订单缺失"三个回补分支全部空转。
        stubPrepareRemoteCalls();
        doAnswer(call -> ((TransactionCallback<?>) call.getArgument(0)).doInTransaction(null))
                .when(transactionTemplate).execute(any());
        var captor = org.mockito.ArgumentCaptor.forClass(
                com.smartlect.api.dto.RushingCouponMessageDTO.class);
        service.prepareCouponRush("user-1", "c1", "rush-key-000000003");
        org.mockito.Mockito.verify(transactionalMqSender).sendAfterCommit(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                captor.capture(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any());
        var payload = captor.getValue();
        org.junit.jupiter.api.Assertions.assertNotNull(payload.getOrderId(), "订单号必须带上");
        org.junit.jupiter.api.Assertions.assertNotNull(payload.getUserId(), "userId 必须带上：消费端回补预占要用");
        org.junit.jupiter.api.Assertions.assertNotNull(payload.getCouponId(), "couponId 必须带上：消费端回补预占要用");
        org.junit.jupiter.api.Assertions.assertNotNull(payload.getUserCouponId(), "userCouponId 必须带上：消费端查占位券要用");
    }
}
