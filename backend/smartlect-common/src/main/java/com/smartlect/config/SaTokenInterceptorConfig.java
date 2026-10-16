package com.smartlect.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.stp.StpUtil;
import com.smartlect.constants.AdminPermissions;
import com.smartlect.interceptor.TrialAdminGuardInterceptor;
import com.smartlect.security.StpAdminLogic;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Sa-Token 服务端注解鉴权（ADR-0011 Step 3）。
 *
 * <p>取代 GlobalOperationAspect + AppInterceptor：
 * 用户端 /api/** 路径由 @SaCheckLogin 拦截（SaInterceptor 全局注册）；
 * 管理端 /admin/** 路径在拦截器内统一走 admin StpLogic 的登录校验 +
 * @SaCheckPermission(type="admin") 的细粒度权限校验。
 *
 * <p>排除路径与网关白名单一致：登录/验证码/公开商品浏览等。
 */
@Configuration
public class SaTokenInterceptorConfig implements WebMvcConfigurer {

    @Autowired
    private AdminContextCleanupInterceptor cleanupInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 用户端：@SaCheckLogin 注解驱动
        registry.addInterceptor(new SaInterceptor())
                .addPathPatterns("/**")
                .excludePathPatterns(
                        "/admin/**", "/internal/**", "/actuator/**",
                        "/api/account/autoLogin", "/api/account/checkCode",
                        "/api/account/register", "/api/account/login",
                        "/api/account/logout", "/api/account/getEmailCode",
                        "/api/account/forgetPassword",
                        "/api/captcha/**", "/api/product/**",
                        "/api/discountCoupon/getDiscountCouponDetail",
                        "/api/discountCoupon/loadDiscountCoupon",
                        "/api/file/getResource");

        // 管理端：统一 admin 登录校验 + AdminSecurityContext 注入 + 注解级权限
        registry.addInterceptor(new SaInterceptor(handle -> {
                    StpAdminLogic.LOGIC.checkLogin();
                    // AppInterceptor 退役后由这里接替：从 Sa-Token session 加载 AdminPrincipalDTO
                    // 注入 AdminSecurityContext（ThreadLocal），供 controller / TrialOrderPrivacy 使用。
                    Object loginId = StpAdminLogic.LOGIC.getLoginId();
                    if (loginId != null) {
                        try {
                            cn.dev33.satoken.session.SaSession session =
                                    StpAdminLogic.LOGIC.getSessionByLoginId(loginId, false);
                            Object principal = session == null ? null : session.get("adminPrincipal");
                            if (principal instanceof com.smartlect.entity.dto.AdminPrincipalDTO dto) {
                                com.smartlect.security.AdminSecurityContext.set(dto);
                            }
                        } catch (Exception ignored) {
                            // session 不可达时 @SaCheckPermission 自然会拒——这里不额外抛错
                        }
                    }
                }))
                .addPathPatterns("/admin/**")
                .excludePathPatterns(
                        "/admin/account/checkCode", "/admin/account/login",
                        "/admin/file/getResource", "/admin/file/getResource/**");
        // 展厅（TRIAL_OPERATOR，公开口令）守卫：读默认允许（隐私清单除外）、写默认拒绝
        // （退款复核显式放行）；@TrialReadable 可显式放宽。见 TrialAdminAccess 的策略说明。
        registry.addInterceptor(new TrialAdminGuardInterceptor())
                .addPathPatterns("/admin/**")
                .excludePathPatterns(
                        "/admin/account/checkCode", "/admin/account/login",
                        "/admin/file/getResource", "/admin/file/getResource/**");

        // ThreadLocal 清理（原 AppInterceptor.afterCompletion 职责）
        registry.addInterceptor(cleanupInterceptor)
                .addPathPatterns("/admin/**");
    }
}
