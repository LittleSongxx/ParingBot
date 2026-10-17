package com.smartlect.biz;

import com.smartlect.api.dto.RefundCouponReturnDTO;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.component.CouponRushStockService;
import com.smartlect.component.DiscountCouponCacheComponent;
import com.smartlect.entity.po.DiscountCoupon;
import com.smartlect.entity.po.UserCoupon;
import com.smartlect.entity.query.DiscountCouponQuery;
import com.smartlect.entity.query.UserCouponQuery;
import com.smartlect.mappers.DiscountCouponMapper;
import com.smartlect.mappers.UserCouponMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 退款全额还券（ADR-0006）：USED→NOUSE 条件更新幂等；券过期/状态不符终态跳过。
 */
@ExtendWith(MockitoExtension.class)
class RefundCouponReturnServiceTest {

    @Mock
    private UserCouponMapper<UserCoupon, UserCouponQuery> userCouponMapper;
    @Mock
    private DiscountCouponMapper<DiscountCoupon, DiscountCouponQuery> discountCouponMapper;
    @Mock
    private CouponRushStockService couponRushStockService;
    @Mock
    private DiscountCouponService discountCouponService;
    @Mock
    private DiscountCouponCacheComponent discountCouponCacheComponent;

    @InjectMocks
    private CouponInternalService service;

    @BeforeEach
    void lenientStubs() {
        lenient().when(userCouponMapper.updateByParam(any(), any())).thenReturn(1);
    }

    @Test
    void usedCouponWithinValidityIsReturnedToUnused() {
        stubUserCoupon(UserCouponStatusEnum.USED.getStatus());
        stubCouponValid();

        assertTrue(service.returnCouponForRefund(new RefundCouponReturnDTO("o1", "p1", "uc-1", "c1")));

        verify(userCouponMapper).updateByParam(any(), any());
    }

    @Test
    void replayedReturnForAlreadyUnusedCouponIsIdempotentSuccess() {
        stubUserCoupon(UserCouponStatusEnum.NOUSE.getStatus());

        assertTrue(service.returnCouponForRefund(new RefundCouponReturnDTO("o1", "p1", "uc-1", "c1")));

        verify(userCouponMapper, never()).updateByParam(any(), any());
    }

    @Test
    void expiredCouponTemplateIsSkippedAsTerminalSuccess() {
        stubUserCoupon(UserCouponStatusEnum.USED.getStatus());
        DiscountCoupon coupon = new DiscountCoupon();
        coupon.setCouponId("c1");
        coupon.setValidEndTime(new Date(System.currentTimeMillis() - 60_000));
        when(discountCouponMapper.selectByCouponId("c1")).thenReturn(coupon);

        assertTrue(service.returnCouponForRefund(new RefundCouponReturnDTO("o1", "p1", "uc-1", "c1")));

        verify(userCouponMapper, never()).updateByParam(any(), any());
    }

    @Test
    void nonUsedCouponStatusIsSkippedAsTerminalSuccess() {
        stubUserCoupon(UserCouponStatusEnum.CANT.getStatus());

        assertTrue(service.returnCouponForRefund(new RefundCouponReturnDTO("o1", "p1", "uc-1", "c1")));

        verify(userCouponMapper, never()).updateByParam(any(), any());
    }

    @Test
    void missingUserCouponIsReportedAsSkipped() {
        when(userCouponMapper.selectByUserCouponId("uc-x")).thenReturn(null);

        assertFalse(service.returnCouponForRefund(new RefundCouponReturnDTO("o1", "p1", "uc-x", "c1")));
    }

    private void stubUserCoupon(Integer status) {
        UserCoupon userCoupon = new UserCoupon();
        userCoupon.setUserCouponId("uc-1");
        userCoupon.setUserId("u1");
        userCoupon.setCouponId("c1");
        userCoupon.setStatus(status);
        when(userCouponMapper.selectByUserCouponId("uc-1")).thenReturn(userCoupon);
    }

    private void stubCouponValid() {
        DiscountCoupon coupon = new DiscountCoupon();
        coupon.setCouponId("c1");
        coupon.setValidEndTime(new Date(System.currentTimeMillis() + 60_000));
        when(discountCouponMapper.selectByCouponId("c1")).thenReturn(coupon);
    }
}
