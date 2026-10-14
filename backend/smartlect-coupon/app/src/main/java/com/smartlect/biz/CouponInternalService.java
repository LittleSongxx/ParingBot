package com.smartlect.biz;

import com.smartlect.api.dto.CouponValidateAndLockDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.dto.UserCouponStatusChangeDTO;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.CouponGrantResultVO;
import com.smartlect.api.vo.CouponLockResultVO;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.api.enums.CouponStatusEnum;
import com.smartlect.api.enums.CouponTypeEnum;
import com.smartlect.api.enums.UserCouponStatusEnum;
import com.smartlect.entity.po.DiscountCoupon;
import com.smartlect.entity.po.UserCoupon;
import com.smartlect.entity.query.DiscountCouponQuery;
import com.smartlect.entity.query.UserCouponQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.component.CouponRushStockService;
import com.smartlect.component.DiscountCouponCacheComponent;
import com.smartlect.mappers.DiscountCouponMapper;
import com.smartlect.mappers.UserCouponMapper;
import com.smartlect.biz.DiscountCouponService;
import com.smartlect.utils.OrderPayAmountUtil;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Date;

@Service
@Slf4j
public class CouponInternalService {

    @Resource
    private UserCouponMapper<UserCoupon, UserCouponQuery> userCouponMapper;
    @Resource
    private DiscountCouponMapper<DiscountCoupon, DiscountCouponQuery> discountCouponMapper;
    @Resource
    private CouponRushStockService couponRushStockService;
    @Resource
    private DiscountCouponService discountCouponService;
    @Resource
    private DiscountCouponCacheComponent discountCouponCacheComponent;

    @Transactional(rollbackFor = Exception.class)
    public CouponLockResultVO validateAndLock(CouponValidateAndLockDTO dto) {
        return validateCoupon(dto, true);
    }

    public CouponLockResultVO preview(CouponValidateAndLockDTO dto) {
        return validateCoupon(dto, false);
    }

    private CouponLockResultVO validateCoupon(CouponValidateAndLockDTO dto, boolean lock) {
        Date now = new Date();
        UserCoupon userCoupon = userCouponMapper.selectByUserCouponId(dto.getUserCouponId());
        if (userCoupon == null || !dto.getUserId().equals(userCoupon.getUserId())) {
            throw new BusinessException("优惠券不存在");
        }
        if (!UserCouponStatusEnum.NOUSE.getStatus().equals(userCoupon.getStatus())) {
            throw new BusinessException("优惠券不可用");
        }
        DiscountCoupon coupon = discountCouponMapper.selectByCouponId(userCoupon.getCouponId());
        if (coupon == null) {
            throw new BusinessException("优惠券不存在");
        }
        if (coupon.getValidStartTime() != null && now.before(coupon.getValidStartTime())) {
            throw new BusinessException("优惠券未到使用时间");
        }
        if (coupon.getValidEndTime() != null && now.after(coupon.getValidEndTime())) {
            throw new BusinessException("优惠券已过期");
        }
        BigDecimal orderAmount = dto.getOrderAmount() == null ? BigDecimal.ZERO : dto.getOrderAmount();
        BigDecimal threshold = coupon.getThresholdAmount() == null ? BigDecimal.ZERO : coupon.getThresholdAmount();
        if (threshold.compareTo(BigDecimal.ZERO) > 0 && orderAmount.compareTo(threshold) < 0) {
            throw new BusinessException("未满足优惠券使用门槛");
        }
        BigDecimal discount = calcCouponDiscount(coupon, orderAmount);
        discount = OrderPayAmountUtil.capCouponDiscountForMinPay(orderAmount, discount);

        CouponLockResultVO result = new CouponLockResultVO();
        result.setCouponId(coupon.getCouponId());
        result.setUserCouponId(dto.getUserCouponId());
        result.setCouponName(coupon.getCouponName());
        result.setDiscountAmount(discount);
        result.setLocked(false);
        if (lock && discount.compareTo(BigDecimal.ZERO) > 0) {
            UserCoupon lockBean = new UserCoupon();
            lockBean.setStatus(UserCouponStatusEnum.CANT.getStatus());
            UserCouponQuery lockQuery = new UserCouponQuery();
            lockQuery.setUserCouponId(dto.getUserCouponId());
            lockQuery.setUserId(dto.getUserId());
            lockQuery.setStatus(UserCouponStatusEnum.NOUSE.getStatus());
            int updated = userCouponMapper.updateByParam(lockBean, lockQuery);
            if (updated != 1) {
                throw new BusinessException("优惠券已被使用");
            }
            result.setLocked(true);
        }
        return result;
    }

    public DiscountCouponVO getCoupon(String couponId) {
        DiscountCoupon coupon = discountCouponMapper.selectByCouponId(couponId);
        if (coupon == null) {
            return null;
        }
        DiscountCouponVO vo = new DiscountCouponVO();
        BeanUtils.copyProperties(coupon, vo);
        return vo;
    }

    public CouponBriefVO getCouponBrief(String couponId) {
        DiscountCoupon coupon = discountCouponMapper.selectByCouponId(couponId);
        if (coupon == null) {
            return null;
        }
        CouponBriefVO vo = new CouponBriefVO();
        vo.setCouponId(coupon.getCouponId());
        vo.setCouponName(coupon.getCouponName());
        vo.setCouponType(coupon.getCouponType());
        return vo;
    }

    public UserCouponVO getUserCoupon(String userCouponId) {
        UserCoupon uc = userCouponMapper.selectByUserCouponId(userCouponId);
        if (uc == null) {
            return null;
        }
        UserCouponVO vo = new UserCouponVO();
        BeanUtils.copyProperties(uc, vo);
        return vo;
    }


    /**
     * 退款全额还券（ADR-0020）：USED→NOUSE 条件更新，幂等可重放。
     * 返回 true 表示终态成功（已还/无需还/券过期跳过），消费端据此确认；
     * false 仅在数据缺失时返回（同样按终态处理并留痕，不无限重投）。
     */
    @Transactional(rollbackFor = Exception.class)
    public boolean returnCouponForRefund(com.smartlect.api.dto.RefundCouponReturnDTO dto) {
        if (dto == null || StringTools.isEmpty(dto.getUserCouponId())) {
            log.warn("退款还券消息字段不完整，跳过 dto={}", dto);
            return false;
        }
        UserCoupon userCoupon = userCouponMapper.selectByUserCouponId(dto.getUserCouponId());
        if (userCoupon == null) {
            log.warn("退款还券：用户券不存在，跳过 userCouponId={}", dto.getUserCouponId());
            return false;
        }
        if (UserCouponStatusEnum.NOUSE.getStatus().equals(userCoupon.getStatus())) {
            // 已返还（重放）或从未核销——幂等成功
            return true;
        }
        if (!UserCouponStatusEnum.USED.getStatus().equals(userCoupon.getStatus())) {
            // CANT 等其它状态不是退款还券的语义范围（如秒杀占位券走独立的激活/释放链）
            log.info("退款还券：用户券状态非已使用，跳过 userCouponId={}, status={}",
                    dto.getUserCouponId(), userCoupon.getStatus());
            return true;
        }
        DiscountCoupon coupon = discountCouponMapper.selectByCouponId(userCoupon.getCouponId());
        Date now = new Date();
        if (coupon != null && coupon.getValidEndTime() != null && now.after(coupon.getValidEndTime())) {
            // 券已过期：还了也用不了，按终态跳过（行业惯例：过期券不返还可用状态）
            log.info("退款还券：券模板已过期，跳过 userCouponId={}, couponId={}",
                    dto.getUserCouponId(), userCoupon.getCouponId());
            return true;
        }
        UserCoupon bean = new UserCoupon();
        bean.setStatus(UserCouponStatusEnum.NOUSE.getStatus());
        bean.setUseTime(null);
        UserCouponQuery query = new UserCouponQuery();
        query.setUserCouponId(userCoupon.getUserCouponId());
        query.setUserId(userCoupon.getUserId());
        query.setStatus(UserCouponStatusEnum.USED.getStatus());
        int updated = userCouponMapper.updateByParam(bean, query);
        if (updated < 1) {
            // 并发下已被他人推进（重放/人工），重读确认幂等
            UserCoupon latest = userCouponMapper.selectByUserCouponId(userCoupon.getUserCouponId());
            if (latest != null && UserCouponStatusEnum.NOUSE.getStatus().equals(latest.getStatus())) {
                return true;
            }
            throw new BusinessException("退款还券失败：用户券状态变化");
        }
        log.info("退款全额还券成功 orderId={}, userCouponId={}", dto.getOrderId(), userCoupon.getUserCouponId());
        return true;
    }

    @Transactional(rollbackFor = Exception.class)
    public void changeUserCouponStatus(UserCouponStatusChangeDTO dto) {
        UserCoupon bean = new UserCoupon();
        bean.setStatus(dto.getToStatus());
        if (dto.getUseTime() != null) {
            bean.setUseTime(dto.getUseTime());
        }
        UserCouponQuery query = new UserCouponQuery();
        query.setUserCouponId(dto.getUserCouponId());
        query.setUserId(dto.getUserId());
        query.setStatus(dto.getFromStatus());
        int updated = userCouponMapper.updateByParam(bean, query);
        if (updated < 1) {
            throw new BusinessException("用户券状态更新失败");
        }
    }

    @Transactional(rollbackFor = Exception.class)
    public void createUserCoupon(UserCouponCreateDTO dto) {
        UserCoupon userCoupon = new UserCoupon();
        userCoupon.setUserCouponId(dto.getUserCouponId());
        userCoupon.setUserId(dto.getUserId());
        userCoupon.setCouponId(dto.getCouponId());
        userCoupon.setStatus(dto.getStatus());
        userCouponMapper.insert(userCoupon);
    }

    @Transactional(rollbackFor = Exception.class)
    public CouponGrantResultVO grantCoupon(UserCouponCreateDTO dto) {
        if (dto == null
                || StringTools.isEmpty(dto.getUserCouponId())
                || StringTools.isEmpty(dto.getUserId())
                || StringTools.isEmpty(dto.getCouponId())
                || !UserCouponStatusEnum.NOUSE.getStatus().equals(dto.getStatus())) {
            throw new BusinessException("发券参数不完整");
        }
        DiscountCoupon locked = discountCouponMapper.selectByCouponIdForUpdate(dto.getCouponId());
        if (locked == null) {
            throw new BusinessException("优惠券不存在");
        }
        UserCoupon existing = userCouponMapper.selectByUserCouponId(dto.getUserCouponId());
        if (existing != null) {
            if (!dto.getUserId().equals(existing.getUserId())
                    || !dto.getCouponId().equals(existing.getCouponId())) {
                throw new BusinessException("用户券业务键冲突");
            }
            return grantResult(true, false, dto.getUserCouponId(), locked.getCouponName());
        }
        assertGrantable(locked, new Date());
        Integer affected = discountCouponMapper.deductStock(dto.getCouponId());
        if (affected == null || affected != 1) {
            return grantResult(false, false, dto.getUserCouponId(), locked.getCouponName());
        }
        UserCoupon userCoupon = new UserCoupon();
        userCoupon.setUserCouponId(dto.getUserCouponId());
        userCoupon.setUserId(dto.getUserId());
        userCoupon.setCouponId(dto.getCouponId());
        userCoupon.setStatus(dto.getStatus());
        userCouponMapper.insertGranted(userCoupon);
        invalidateCacheAfterCommit(dto.getCouponId());
        return grantResult(true, true, dto.getUserCouponId(), locked.getCouponName());
    }

    @Transactional(rollbackFor = Exception.class)
    public int deductStock(String couponId) {
        if (StringTools.isEmpty(couponId)) {
            throw new BusinessException("优惠券ID为空");
        }
        DiscountCoupon locked = discountCouponMapper.selectByCouponIdForUpdate(couponId);
        if (locked == null) {
            throw new BusinessException("优惠券不存在");
        }
        Integer affected = discountCouponMapper.deductStock(couponId);
        return affected == null ? 0 : affected;
    }

    private CouponGrantResultVO grantResult(
            boolean granted,
            boolean newlyGranted,
            String userCouponId,
            String couponName) {
        CouponGrantResultVO result = new CouponGrantResultVO();
        result.setGranted(granted);
        result.setNewlyGranted(newlyGranted);
        result.setUserCouponId(userCouponId);
        result.setCouponName(couponName);
        return result;
    }

    private void assertGrantable(DiscountCoupon coupon, Date now) {
        if (!CouponStatusEnum.NORMAL.getStatus().equals(coupon.getStatus())) {
            throw new BusinessException("优惠券当前不可发放");
        }
        if (coupon.getValidStartTime() != null && now.before(coupon.getValidStartTime())) {
            throw new BusinessException("优惠券未到发放时间");
        }
        if (coupon.getValidEndTime() != null && now.after(coupon.getValidEndTime())) {
            throw new BusinessException("优惠券已过期");
        }
    }

    private void invalidateCacheAfterCommit(String couponId) {
        Runnable action = () -> {
            try {
                discountCouponCacheComponent.invalidateAfterWrite(couponId);
            } catch (Exception e) {
                log.warn("发券后优惠券缓存失效失败，数据库库存仍为权威来源 couponId={}", couponId, e);
            }
        };
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    action.run();
                }
            });
            return;
        }
        action.run();
    }

    public void assertRushNotBlocked(String couponId) {
        couponRushStockService.assertRushNotBlocked(couponId);
    }

    public boolean hasAvailableRushStock(String couponId) {
        return couponRushStockService.hasAvailableStock(couponId);
    }

    public void syncRushStockFromDbIfRedisZero(String couponId) {
        couponRushStockService.syncFromDbIfRedisZero(couponId);
    }

    public void releaseRushRedisReserve(String couponId, String userId) {
        discountCouponService.releaseRushRedisReserve(couponId, userId);
    }

    public void releaseRushCouponReserve(String couponId, String userId) {
        discountCouponService.releaseRushCouponReserve(couponId, userId);
    }

    public void invalidateCouponCache(String couponId) {
        discountCouponCacheComponent.invalidateAfterWrite(couponId);
    }

    private BigDecimal calcCouponDiscount(DiscountCoupon coupon, BigDecimal amount) {
        if (coupon == null || amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            return BigDecimal.ZERO;
        }
        Integer type = coupon.getCouponType();
        BigDecimal discount = BigDecimal.ZERO;
        if (CouponTypeEnum.FULL.getStatus().equals(type) || CouponTypeEnum.NOTHRESHOLD.getStatus().equals(type)) {
            discount = coupon.getDiscountAmount() == null ? BigDecimal.ZERO : coupon.getDiscountAmount();
        } else if (CouponTypeEnum.DISCOUNT.getStatus().equals(type)) {
            BigDecimal rate = coupon.getDiscountRate();
            if (rate == null || rate.compareTo(BigDecimal.ZERO) <= 0 || rate.compareTo(BigDecimal.ONE) > 0) {
                throw new com.smartlect.exception.BusinessException("优惠券折扣配置异常");
            }
            discount = amount.multiply(BigDecimal.ONE.subtract(rate));
        }
        if (discount.compareTo(BigDecimal.ZERO) < 0) {
            discount = BigDecimal.ZERO;
        }
        if (discount.compareTo(amount) > 0) {
            discount = amount;
        }
        return discount.setScale(2, RoundingMode.HALF_UP);
    }
}
