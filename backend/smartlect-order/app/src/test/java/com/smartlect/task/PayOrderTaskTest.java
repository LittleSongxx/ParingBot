package com.smartlect.task;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.component.RedisComponent;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 支付轮询对账（ADR-0018）：旧实现被永不置位的 isPayTradeInitiated 过滤闸卡成死路径，
 * 新实现按"创建超过 N 分钟仍待付款"直接查渠道。这里锁定轮询集合与逐单容错语义。
 */
@ExtendWith(MockitoExtension.class)
class PayOrderTaskTest {

    @Mock
    private AppConfig appConfig;
    @Mock
    private OrderInfoService orderInfoService;
    @Mock
    private PayFeignSupport payFeignSupport;
    @Mock
    private RedisComponent redisComponent;

    @InjectMocks
    private PayOrderTask task;

    @BeforeEach
    void setUp() {
        when(appConfig.getAutoCheckpay()).thenReturn(true);
        when(redisComponent.setIfAbsent(anyString(), anyString(), anyLong(), any())).thenReturn(true);
        ReflectionTestUtils.setField(task, "pollMinAgeSeconds", 180);
        ReflectionTestUtils.setField(task, "pollBatchSize", 200);
        ReflectionTestUtils.setField(task, "applicationName", "smartlect-order");
    }

    @Test
    void pollsOnlyAgedWaitPaymentOrdersAndDrivesPaySuccess() {
        OrderInfo order = new OrderInfo();
        order.setOrderId("o1");
        order.setPayOrderId("pay-1");
        order.setPayChannel("mock");
        when(orderInfoService.findWaitPaymentPollList(3, 200)).thenReturn(List.of(order));
        when(payFeignSupport.queryOrder("pay-1", "mock")).thenReturn(new PayOrderNotifyDTO("pay-1", "ch-1"));

        task.pollPayOrders();

        verify(orderInfoService).findWaitPaymentPollList(3, 200);
        verify(orderInfoService).paySuccess(any(PayOrderNotifyDTO.class));
    }

    @Test
    void channelPendingResultIsSkippedWithoutPaySuccess() {
        OrderInfo order = new OrderInfo();
        order.setOrderId("o1");
        order.setPayOrderId("pay-1");
        order.setPayChannel("mock");
        when(orderInfoService.findWaitPaymentPollList(anyInt(), anyInt())).thenReturn(List.of(order));
        when(payFeignSupport.queryOrder("pay-1", "mock")).thenReturn(null);

        task.pollPayOrders();

        verify(orderInfoService, never()).paySuccess(any());
    }

    @Test
    void singleOrderFailureDoesNotBlockTheRestOfBatch() {
        OrderInfo bad = order("o1", "pay-1", "mock");
        OrderInfo good = order("o2", "pay-2", "mock");
        when(orderInfoService.findWaitPaymentPollList(anyInt(), anyInt())).thenReturn(List.of(bad, good));
        when(payFeignSupport.queryOrder("pay-1", "mock")).thenThrow(new BusinessException("渠道暂时不可用"));
        when(payFeignSupport.queryOrder("pay-2", "mock")).thenReturn(new PayOrderNotifyDTO("pay-2", "ch-2"));

        task.pollPayOrders();

        verify(orderInfoService).paySuccess(any(PayOrderNotifyDTO.class));
    }

    @Test
    void orderWithoutPayOrderIdOrChannelIsIgnored() {
        OrderInfo noPayId = order("o1", null, "mock");
        OrderInfo noChannel = order("o2", "pay-2", null);
        when(orderInfoService.findWaitPaymentPollList(anyInt(), anyInt())).thenReturn(List.of(noPayId, noChannel));

        task.pollPayOrders();

        verify(payFeignSupport, never()).queryOrder(anyString(), anyString());
        verify(orderInfoService, never()).paySuccess(any());
    }

    private static OrderInfo order(String orderId, String payOrderId, String payChannel) {
        OrderInfo order = new OrderInfo();
        order.setOrderId(orderId);
        order.setPayOrderId(payOrderId);
        order.setPayChannel(payChannel);
        return order;
    }
}
