package com.smartlect.api.support;

import com.smartlect.api.dubbo.CouponDubboService;
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
import com.smartlect.compensation.UserCouponStatusCompensatePort;
import jakarta.annotation.Resource;
import org.apache.dubbo.config.annotation.DubboReference;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.Date;

@Component
public class CouponRpcSupport implements UserCouponStatusCompensatePort {

    @DubboReference
    private CouponDubboService couponDubboService;
    @Resource
    private RpcResponseSupport rpcResponseSupport;

    public CouponLockResultVO validateAndLock(String userId, String userCouponId, BigDecimal orderAmount) {
        CouponValidateAndLockDTO dto = new CouponValidateAndLockDTO();
        dto.setUserId(userId);
        dto.setUserCouponId(userCouponId);
        dto.setOrderAmount(orderAmount);
        return rpcResponseSupport.call(() -> couponDubboService.validateAndLock(dto, userId), "优惠券校验失败");
    }

    public CouponLockResultVO preview(String userId, String userCouponId, BigDecimal orderAmount) {
        CouponValidateAndLockDTO dto = new CouponValidateAndLockDTO();
        dto.setUserId(userId);
        dto.setUserCouponId(userCouponId);
        dto.setOrderAmount(orderAmount);
        return rpcResponseSupport.call(() -> couponDubboService.preview(dto, userId), "优惠券预览失败");
    }

    public DiscountCouponVO getCoupon(String couponId) {
        return rpcResponseSupport.call(() -> couponDubboService.getCoupon(new CouponIdDTO(couponId)), "查询优惠券失败");
    }

    public CouponBriefVO getCouponBrief(String couponId) {
        return rpcResponseSupport.call(
                () -> couponDubboService.getCouponBrief(new CouponIdDTO(couponId)), "查询优惠券失败");
    }

    public UserCouponVO getUserCoupon(String userCouponId) {
        return rpcResponseSupport.call(
                () -> couponDubboService.getUserCoupon(new UserCouponIdDTO(userCouponId)), "查询用户券失败");
    }

    @Override
    public void changeUserCouponStatus(String userCouponId, String userId, Integer fromStatus, Integer toStatus, Date useTime) {
        UserCouponStatusChangeDTO dto = new UserCouponStatusChangeDTO();
        dto.setUserCouponId(userCouponId);
        dto.setUserId(userId);
        dto.setFromStatus(fromStatus);
        dto.setToStatus(toStatus);
        dto.setUseTime(useTime);
        rpcResponseSupport.run(() -> couponDubboService.changeUserCouponStatus(dto, userId), "更新用户券状态失败");
    }

    public void createUserCoupon(UserCouponCreateDTO dto) {
        rpcResponseSupport.run(() -> couponDubboService.createUserCoupon(dto, dto.getUserId()), "创建用户券失败");
    }

    public CouponGrantResultVO grantCoupon(UserCouponCreateDTO dto) {
        return rpcResponseSupport.call(
                () -> couponDubboService.grantCoupon(dto, dto.getUserId()), "发放用户券失败");
    }

    public int deductStock(String couponId, String userId) {
        StockChangeResultVO vo = rpcResponseSupport.call(
                () -> couponDubboService.deductStock(new CouponIdDTO(couponId), userId), "扣减券库存失败");
        return vo == null || vo.getAffectedRows() == null ? 0 : vo.getAffectedRows();
    }

    public void assertRushNotBlocked(String couponId) {
        rpcResponseSupport.run(
                () -> couponDubboService.assertRushNotBlocked(new CouponRushOpsDTO(couponId)),
                "秒杀库存校验失败");
    }

    public boolean hasAvailableRushStock(String couponId) {
        Boolean ok = rpcResponseSupport.call(
                () -> couponDubboService.hasAvailableRushStock(new CouponRushOpsDTO(couponId)),
                "查询秒杀库存失败");
        return Boolean.TRUE.equals(ok);
    }

    public void syncRushStockFromDbIfRedisZero(String couponId) {
        rpcResponseSupport.run(
                () -> couponDubboService.syncRushStockFromDbIfRedisZero(new CouponRushOpsDTO(couponId)),
                "同步秒杀库存失败");
    }

    public void releaseRushRedisReserve(String couponId, String userId) {
        rpcResponseSupport.run(
                () -> couponDubboService.releaseRushRedisReserve(new CouponRushOpsDTO(couponId, userId)),
                "回滚秒杀预占失败");
    }

    public void releaseRushCouponReserve(String couponId, String userId) {
        rpcResponseSupport.run(
                () -> couponDubboService.releaseRushCouponReserve(new CouponRushOpsDTO(couponId, userId)),
                "回滚秒杀券库存失败");
    }

    public void invalidateCouponCache(String couponId) {
        rpcResponseSupport.run(
                () -> couponDubboService.invalidateCouponCache(new CouponRushOpsDTO(couponId)),
                "刷新优惠券缓存失败");
    }
}
