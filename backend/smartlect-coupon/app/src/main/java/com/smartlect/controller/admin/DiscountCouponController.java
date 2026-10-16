package com.smartlect.controller.admin;

import com.smartlect.component.CouponRushStockService;
import cn.dev33.satoken.annotation.SaCheckPermission;
import cn.dev33.satoken.annotation.SaMode;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.api.dto.CouponRushStockReconcileDTO;
import com.smartlect.annotation.AdminSensitiveConfirm;
import com.smartlect.api.dto.DiscountCouponDTO;
import com.smartlect.entity.po.DiscountCoupon;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.DiscountCouponService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RequestMapping("/admin/discountCoupon")
@RestController("adminDiscountCouponController")
// 读/写拆分（2026-10-16 审计）：展厅（TRIAL_OPERATOR，口令公开）的菜单挂着券管理页，
// 但类级注解只认 coupon:manage——展厅读列表直接 NotPermissionException（线上实测 500）。
// 现在注解层放开 admin:trial（与助手侧 admin API 的 require_any(admin:trial) 同口径），
// 写接口由 TrialAdminAccess 的拒绝清单兜底（saveDiscountCoupon / updateDiscountCouponStatus /
// warmupRushStock / reconcileRushStock 四条都在清单里，门禁脚本强制）。
// 注意方法级 @SaCheckPermission 会叠加而非覆盖类级：改这里时不要只在方法上加（类级先抛）。
@SaCheckPermission(value = {"coupon:manage", AdminPermissions.ADMIN_TRIAL}, mode = SaMode.OR, type = "admin")
public class DiscountCouponController extends com.smartlect.controller.admin.ABaseController{

    @Resource
    private DiscountCouponService discountCouponService;
    @Resource
    private CouponRushStockService couponRushStockService;

    // 新增/修改优惠券
    @PostMapping("/saveDiscountCoupon")
    public ResponseVO saveDiscountCoupon(DiscountCouponDTO discountCoupon){
        discountCouponService.saveDiscountCoupon(discountCoupon);
        return getSuccessResponseVO(null);
    }

    // 获取所有优惠券
    @PostMapping("/loadDiscountCoupon")
    public ResponseVO loadDiscountCoupon(Integer pageNo, Integer pageSize, String couponNameFuzzy, Integer couponType, Integer status){
        PaginationResultVO resultVO = discountCouponService.loadDiscountCoupon4Admin(pageNo, pageSize, couponNameFuzzy, couponType, status);
        return getSuccessResponseVO(resultVO);
    }

    // 获取优惠券详情信息
    @PostMapping("/getDiscountCouponInfo")
    public ResponseVO getDiscountCouponInfo(String couponId){
        DiscountCoupon discountCoupon = discountCouponService.getDiscountCouponByCouponId(couponId);
        return getSuccessResponseVO(discountCoupon);
    }

    // 更新优惠券状态
    @PostMapping("/updateDiscountCouponStatus")
    @AdminSensitiveConfirm
    public ResponseVO updateDiscountCouponStatus(String couponId, Integer status){
        DiscountCoupon discountCoupon = discountCouponService.getDiscountCouponByCouponId(couponId);
        discountCoupon.setStatus(status);
        discountCouponService.updateDiscountCouponByCouponId(discountCoupon, couponId);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/warmupRushStock")
    public ResponseVO warmupRushStock(String couponId) {
        if (StringTools.isEmpty(couponId)) {
            int count = couponRushStockService.warmupAllRushingFromDb();
            return getSuccessResponseVO(count);
        }
        DiscountCoupon coupon = discountCouponService.getDiscountCouponByCouponId(couponId);
        if (coupon == null) {
            return getSuccessResponseVO(null);
        }
        couponRushStockService.warmupStock(couponId, coupon.getRemainCount());
        return getSuccessResponseVO(coupon.getRemainCount());
    }

    @PostMapping("/reconcileRushStock")
    public ResponseVO reconcileRushStock(String couponId) {
        if (StringTools.isEmpty(couponId)) {
            List<CouponRushStockReconcileDTO> list = couponRushStockService.reconcileAllRushing();
            return getSuccessResponseVO(list);
        }
        return getSuccessResponseVO(couponRushStockService.reconcileOne(couponId));
    }
}
