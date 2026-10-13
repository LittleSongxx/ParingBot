package com.smartlect.dubbo;

import com.smartlect.api.dubbo.CouponDubboService;
import com.smartlect.api.dto.*;
import com.smartlect.api.vo.*;
import com.smartlect.entity.vo.*;
import jakarta.annotation.Resource;
import com.smartlect.controller.internal.CouponInternalController;
import org.apache.dubbo.config.annotation.DubboService;

/**
 * coupon 域 Dubbo provider：直接委托 internal controller（与 HTTP 通道共用
 * 校验、ResponseVO 包装与全部业务逻辑）。
 */
@DubboService
public class CouponDubboServiceImpl implements CouponDubboService {

    @Resource
    private CouponInternalController couponInternalController;

    @Override
    public ResponseVO<CouponLockResultVO> validateAndLock(CouponValidateAndLockDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.validateAndLock(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<CouponLockResultVO> preview(CouponValidateAndLockDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.preview(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<DiscountCouponVO> getCoupon(CouponIdDTO dto) {
        return couponInternalController.getCoupon(dto);
    }

    @Override
    public ResponseVO<CouponBriefVO> getCouponBrief(CouponIdDTO dto) {
        return couponInternalController.getCouponBrief(dto);
    }

    @Override
    public ResponseVO<UserCouponVO> getUserCoupon(UserCouponIdDTO dto) {
        return couponInternalController.getUserCoupon(dto);
    }

    @Override
    public ResponseVO<Void> changeUserCouponStatus(UserCouponStatusChangeDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.changeUserCouponStatus(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<Void> createUserCoupon(UserCouponCreateDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.createUserCoupon(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<CouponGrantResultVO> grantCoupon(UserCouponCreateDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.grantCoupon(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<StockChangeResultVO> deductStock(CouponIdDTO dto, String userId) {
        com.smartlect.security.DelegatedUserIdentity.setDubboDelegated(userId);
        try {
            return couponInternalController.deductStock(dto);
        } finally {
            com.smartlect.security.DelegatedUserIdentity.clearDubboDelegated();
        }
    }

    @Override
    public ResponseVO<Void> assertRushNotBlocked(CouponRushOpsDTO dto) {
        return couponInternalController.assertRushNotBlocked(dto);
    }

    @Override
    public ResponseVO<Boolean> hasAvailableRushStock(CouponRushOpsDTO dto) {
        return couponInternalController.hasAvailableRushStock(dto);
    }

    @Override
    public ResponseVO<Void> syncRushStockFromDbIfRedisZero(CouponRushOpsDTO dto) {
        return couponInternalController.syncRushStockFromDbIfRedisZero(dto);
    }

    @Override
    public ResponseVO<Void> releaseRushRedisReserve(CouponRushOpsDTO dto) {
        return couponInternalController.releaseRushRedisReserve(dto);
    }

    @Override
    public ResponseVO<Void> releaseRushCouponReserve(CouponRushOpsDTO dto) {
        return couponInternalController.releaseRushCouponReserve(dto);
    }

    @Override
    public ResponseVO<Void> invalidateCouponCache(CouponRushOpsDTO dto) {
        return couponInternalController.invalidateCouponCache(dto);
    }

}
