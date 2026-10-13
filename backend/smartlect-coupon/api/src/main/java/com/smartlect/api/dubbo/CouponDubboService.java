package com.smartlect.api.dubbo;

import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.api.dto.CouponIdDTO;
import com.smartlect.api.dto.CouponRushOpsDTO;
import com.smartlect.api.dto.CouponValidateAndLockDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.dto.UserCouponIdDTO;
import com.smartlect.api.dto.UserCouponStatusChangeDTO;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.CouponGrantResultVO;
import com.smartlect.api.vo.CouponLockResultVO;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.api.vo.UserCouponVO;


/**
 * coupon 域内部 Dubbo 契约（取代原 FeignClient，方法签名一致；
 * HTTP /internal 端点保留给 assistant 与运维，双通道共用同一 Service 层）。
 */
public interface CouponDubboService {

    ResponseVO<CouponLockResultVO> validateAndLock(CouponValidateAndLockDTO dto, String userId);

    ResponseVO<CouponLockResultVO> preview(CouponValidateAndLockDTO dto, String userId);

    ResponseVO<DiscountCouponVO> getCoupon(CouponIdDTO dto);

    ResponseVO<CouponBriefVO> getCouponBrief(CouponIdDTO dto);

    ResponseVO<UserCouponVO> getUserCoupon(UserCouponIdDTO dto);

    ResponseVO<Void> changeUserCouponStatus(UserCouponStatusChangeDTO dto, String userId);

    ResponseVO<Void> createUserCoupon(UserCouponCreateDTO dto, String userId);

    ResponseVO<CouponGrantResultVO> grantCoupon(UserCouponCreateDTO dto, String userId);

    ResponseVO<StockChangeResultVO> deductStock(CouponIdDTO dto, String userId);

    ResponseVO<Void> assertRushNotBlocked(CouponRushOpsDTO dto);

    ResponseVO<Boolean> hasAvailableRushStock(CouponRushOpsDTO dto);

    ResponseVO<Void> syncRushStockFromDbIfRedisZero(CouponRushOpsDTO dto);

    ResponseVO<Void> releaseRushRedisReserve(CouponRushOpsDTO dto);

    ResponseVO<Void> releaseRushCouponReserve(CouponRushOpsDTO dto);

    ResponseVO<Void> invalidateCouponCache(CouponRushOpsDTO dto);

}
