package com.smartlect.biz;

import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.enums.CouponStatusEnum;
import com.smartlect.api.vo.CouponGrantResultVO;
import com.smartlect.component.CouponRushStockService;
import com.smartlect.component.DiscountCouponCacheComponent;
import com.smartlect.entity.po.DiscountCoupon;
import com.smartlect.entity.po.UserCoupon;
import com.smartlect.entity.query.DiscountCouponQuery;
import com.smartlect.entity.query.UserCouponQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.DiscountCouponMapper;
import com.smartlect.mappers.UserCouponMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CouponInternalServiceTest {

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

    @Test
    void retryReturnsExistingGrantWithoutDeductingStockAgain() {
        when(discountCouponMapper.selectByCouponIdForUpdate("c1")).thenReturn(coupon());
        UserCoupon existing = new UserCoupon();
        existing.setUserCouponId("uc1");
        existing.setUserId("u1");
        existing.setCouponId("c1");
        when(userCouponMapper.selectByUserCouponId("uc1")).thenReturn(existing);

        CouponGrantResultVO result = service.grantCoupon(dto());

        assertTrue(result.getGranted());
        assertFalse(result.getNewlyGranted());
        verify(discountCouponMapper, never()).deductStock("c1");
    }

    @Test
    void newGrantDeductsAndCreatesInTheSameServiceTransaction() {
        when(discountCouponMapper.selectByCouponIdForUpdate("c1")).thenReturn(coupon());
        when(discountCouponMapper.deductStock("c1")).thenReturn(1);

        CouponGrantResultVO result = service.grantCoupon(dto());

        assertTrue(result.getGranted());
        assertTrue(result.getNewlyGranted());
        verify(userCouponMapper).insertGranted(any(UserCoupon.class));
        verify(discountCouponCacheComponent).invalidateAfterWrite("c1");
    }

    @Test
    void conflictingStableIdIsRejected() {
        when(discountCouponMapper.selectByCouponIdForUpdate("c1")).thenReturn(coupon());
        UserCoupon existing = new UserCoupon();
        existing.setUserCouponId("uc1");
        existing.setUserId("other");
        existing.setCouponId("c1");
        when(userCouponMapper.selectByUserCouponId("uc1")).thenReturn(existing);

        assertThrows(BusinessException.class, () -> service.grantCoupon(dto()));
    }

    @Test
    void newGrantRejectsInactiveCouponBeforeStockDeduction() {
        DiscountCoupon coupon = coupon();
        coupon.setStatus(CouponStatusEnum.STOP.getStatus());
        when(discountCouponMapper.selectByCouponIdForUpdate("c1")).thenReturn(coupon);

        assertThrows(BusinessException.class, () -> service.grantCoupon(dto()));

        verify(discountCouponMapper, never()).deductStock("c1");
        verify(userCouponMapper, never()).insertGranted(any(UserCoupon.class));
    }

    @Test
    void cacheFailureAfterGrantDoesNotTurnSuccessIntoFailure() {
        when(discountCouponMapper.selectByCouponIdForUpdate("c1")).thenReturn(coupon());
        when(discountCouponMapper.deductStock("c1")).thenReturn(1);
        org.mockito.Mockito.doThrow(new IllegalStateException("redis unavailable"))
                .when(discountCouponCacheComponent).invalidateAfterWrite("c1");

        CouponGrantResultVO result = assertDoesNotThrow(() -> service.grantCoupon(dto()));

        assertTrue(result.getGranted());
        assertTrue(result.getNewlyGranted());
    }

    @Test
    void previewUsesSameDiscountWithoutLockAndRejectsAnotherOwner() {
        UserCoupon owned = new UserCoupon();
        owned.setUserId("u1");
        owned.setCouponId("c1");
        owned.setStatus(com.smartlect.api.enums.UserCouponStatusEnum.NOUSE.getStatus());
        when(userCouponMapper.selectByUserCouponId("uc1")).thenReturn(owned);
        DiscountCoupon coupon = coupon();
        coupon.setCouponType(com.smartlect.api.enums.CouponTypeEnum.NOTHRESHOLD.getStatus());
        coupon.setDiscountAmount(new java.math.BigDecimal("2.00"));
        when(discountCouponMapper.selectByCouponId("c1")).thenReturn(coupon);
        com.smartlect.api.dto.CouponValidateAndLockDTO request = new com.smartlect.api.dto.CouponValidateAndLockDTO();
        request.setUserId("u1");
        request.setUserCouponId("uc1");
        request.setOrderAmount(new java.math.BigDecimal("10.00"));
        var preview = service.preview(request);
        assertFalse(preview.getLocked());
        verify(userCouponMapper, never()).updateByParam(any(), any());
        when(userCouponMapper.updateByParam(any(), any())).thenReturn(1);
        var locked = service.validateAndLock(request);
        assertTrue(locked.getLocked());
        org.junit.jupiter.api.Assertions.assertEquals(preview.getDiscountAmount(), locked.getDiscountAmount());
        request.setUserId("other");
        assertThrows(BusinessException.class, () -> service.preview(request));
    }

    @Test
    void stoppedTemplateRejectsPreviewAndLock() {
        UserCoupon owned = new UserCoupon();
        owned.setUserId("u1");
        owned.setCouponId("c1");
        owned.setStatus(com.smartlect.api.enums.UserCouponStatusEnum.NOUSE.getStatus());
        when(userCouponMapper.selectByUserCouponId("uc1")).thenReturn(owned);
        DiscountCoupon coupon = coupon();
        coupon.setStatus(CouponStatusEnum.STOP.getStatus());
        when(discountCouponMapper.selectByCouponId("c1")).thenReturn(coupon);

        com.smartlect.api.dto.CouponValidateAndLockDTO request = new com.smartlect.api.dto.CouponValidateAndLockDTO();
        request.setUserId("u1");
        request.setUserCouponId("uc1");
        request.setOrderAmount(new java.math.BigDecimal("10.00"));

        assertThrows(BusinessException.class, () -> service.preview(request));
        assertThrows(BusinessException.class, () -> service.validateAndLock(request));
        verify(userCouponMapper, never()).updateByParam(any(), any());
    }

    @Test
    void finishedTemplateStillAllowsAlreadyIssuedCoupon() {
        UserCoupon owned = new UserCoupon();
        owned.setUserId("u1");
        owned.setCouponId("c1");
        owned.setStatus(com.smartlect.api.enums.UserCouponStatusEnum.NOUSE.getStatus());
        when(userCouponMapper.selectByUserCouponId("uc1")).thenReturn(owned);
        DiscountCoupon coupon = coupon();
        coupon.setStatus(CouponStatusEnum.FINISH.getStatus());
        coupon.setCouponType(com.smartlect.api.enums.CouponTypeEnum.NOTHRESHOLD.getStatus());
        coupon.setDiscountAmount(new java.math.BigDecimal("2.00"));
        when(discountCouponMapper.selectByCouponId("c1")).thenReturn(coupon);

        com.smartlect.api.dto.CouponValidateAndLockDTO request = new com.smartlect.api.dto.CouponValidateAndLockDTO();
        request.setUserId("u1");
        request.setUserCouponId("uc1");
        request.setOrderAmount(new java.math.BigDecimal("10.00"));

        assertDoesNotThrow(() -> service.preview(request));
    }

    private static DiscountCoupon coupon() {
        DiscountCoupon coupon = new DiscountCoupon();
        coupon.setCouponId("c1");
        coupon.setCouponName("测试券");
        coupon.setStatus(CouponStatusEnum.NORMAL.getStatus());
        coupon.setValidStartTime(new Date(System.currentTimeMillis() - 60_000L));
        coupon.setValidEndTime(new Date(System.currentTimeMillis() + 60_000L));
        return coupon;
    }

    private static UserCouponCreateDTO dto() {
        UserCouponCreateDTO dto = new UserCouponCreateDTO();
        dto.setUserCouponId("uc1");
        dto.setUserId("u1");
        dto.setCouponId("c1");
        dto.setStatus(0);
        return dto;
    }
}
