package com.smartlect.controller.admin;

import com.smartlect.component.CouponRushStockService;
import cn.dev33.satoken.annotation.SaCheckPermission;
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
// 读/写拆分（2026-10-16 审计）：类级注解此前让"查看券"也要求 coupon:manage，
// 展厅（TRIAL_OPERATOR）连券列表都读不到、而前端菜单却挂着券管理页。现在读接口放开给
// 展厅，写接口保持仅超管；展厅的写还会被 TrialAdminAccess 的拒绝清单再挡一次。
@SaCheckPermission(value = {"coupon:manage"}, orRole = "SUPER_ADMIN", type = "admin")
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
    @SaCheckPermission(value = {"coupon:manage"}, orRole = {"SUPER_ADMIN", "TRIAL_OPERATOR"}, type = "admin")
    @PostMapping("/loadDiscountCoupon")
    public ResponseVO loadDiscountCoupon(Integer pageNo, Integer pageSize, String couponNameFuzzy, Integer couponType, Integer status){
        PaginationResultVO resultVO = discountCouponService.loadDiscountCoupon4Admin(pageNo, pageSize, couponNameFuzzy, couponType, status);
        return getSuccessResponseVO(resultVO);
    }

    // 获取优惠券详情信息
    @SaCheckPermission(value = {"coupon:manage"}, orRole = {"SUPER_ADMIN", "TRIAL_OPERATOR"}, type = "admin")
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
