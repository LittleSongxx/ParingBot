package com.smartlect.interceptor;

import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.security.AdminSecurityContext;
import com.smartlect.security.TrialAdminAccess;
import com.smartlect.security.TrialReadable;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;

/**
 * 展厅账号（TRIAL_OPERATOR，口令公开在 README）的服务端守卫。
 *
 * <p>在管理端链上位于 SaInterceptor 之后：那时 AdminSecurityContext 已注入 principal，
 * 但注解级权限检查也已在同一拦截器里完成——两道闸互不替代：
 * 注解管"该角色有没有这个权限点"，本拦截器管"展厅身份本身能做什么"。</p>
 *
 * <p>策略见 {@link TrialAdminAccess}：读默认允许（隐私清单除外）、写默认拒绝
 * （退款复核显式放行）、方法上的 {@link TrialReadable} 可显式放宽。</p>
 */
@Slf4j
public class TrialAdminGuardInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        AdminPrincipalDTO principal = AdminSecurityContext.current();
        if (principal == null
                || !TrialAdminAccess.isTrial(principal.getRoles(), principal.getPermissions())) {
            return true;
        }
        if (handler instanceof HandlerMethod method && method.hasMethodAnnotation(TrialReadable.class)) {
            return true;
        }
        String path = request.getRequestURI();
        if (TrialAdminAccess.allows(path)) {
            return true;
        }
        log.warn("展厅账号被服务端拒绝：{} {}（策略：读默认允许/写默认拒绝，见 TrialAdminAccess）",
                request.getMethod(), path);
        // 403 + 与前端一致的中文文案（前端 constants/trial.js 的 TRIAL_ADMIN_DENIED）
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json;charset=UTF-8");
        try {
            response.getWriter().write("{\"status\":\"error\",\"code\":403,\"info\":\""
                    + TrialAdminAccess.DENIED_MESSAGE + "\",\"data\":null}");
        } catch (java.io.IOException ignored) {
            // 响应已提交/断开：拒绝语义已经生效，无需再抛
        }
        return false;
    }
}
