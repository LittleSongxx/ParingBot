package com.smartlect.component;

import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.api.support.OrderRpcSupport;
import com.smartlect.biz.DiscountCouponService;
import com.smartlect.biz.UserCouponService;
import com.smartlect.mq.RocketMqTopics;
import com.smartlect.mq.SmartlectMqMessage;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RocketMqOrderDeadListListenerTest {

    @Mock
    private DiscountCouponService discountCouponService;
    @Mock
    private UserCouponService userCouponService;
    @Mock
    private OrderRpcSupport orderRpcSupport;
    @InjectMocks
    private RocketMqOrderDeadListListener listener;

    @Test
    void preOrderTimeoutReleasesCouponReserveWhenNoOrderWasCreated() {
        RushingCouponMessageDTO payload = payload(null);
        when(userCouponService.getUserCouponByUserCouponId("uc-1")).thenReturn(null);

        listener.onMessage(payload, message());

        verify(discountCouponService).releaseRushCouponReserve("coupon-1", "user-1");
    }

    @Test
    void missingOrderRollbackOnlyReleasesRedisReserve() {
        RushingCouponMessageDTO payload = payload("order-1");
        when(userCouponService.getUserCouponByUserCouponId("uc-1")).thenReturn(null);
        when(orderRpcSupport.getOrder("order-1")).thenReturn(null);

        listener.onMessage(payload, message());

        verify(discountCouponService).releaseRushRedisReserve("coupon-1", "user-1");
    }

    @Test
    void listenerDoesNotWrapRemoteCallsInOneDatabaseTransaction() throws NoSuchMethodException {
        assertNull(RocketMqOrderDeadListListener.class
                .getMethod("onMessage", RushingCouponMessageDTO.class, SmartlectMqMessage.class)
                .getAnnotation(Transactional.class));
    }

    @Test
    void subscriptionPointsToRushTimeoutTopic() {
        assertEquals(RocketMqTopics.TOPIC_DELAY, listener.subscription().topic());
        assertEquals(RocketMqTopics.TAG_RUSH_TIMEOUT, listener.subscription().tag());
    }

    private static RushingCouponMessageDTO payload(String orderId) {
        RushingCouponMessageDTO payload = new RushingCouponMessageDTO();
        payload.setUserId("user-1");
        payload.setCouponId("coupon-1");
        payload.setUserCouponId("uc-1");
        payload.setOrderId(orderId);
        return payload;
    }

    private static SmartlectMqMessage message() {
        return SmartlectMqMessage.of(RocketMqTopics.TOPIC_RUSH, RocketMqTopics.TAG_RUSH_TIMEOUT,
                new byte[0], "msg-1", new HashMap<>());
    }
}
