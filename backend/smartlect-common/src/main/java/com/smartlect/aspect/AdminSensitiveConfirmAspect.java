package com.smartlect.aspect;

import com.smartlect.annotation.AdminSensitiveConfirm;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.exception.BusinessException;
import com.smartlect.security.AdminCredentialVerifier;
import com.smartlect.security.AdminSecurityContext;
import com.smartlect.service.PasswordService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

@Slf4j
@Aspect
@Component
public class AdminSensitiveConfirmAspect {

    public static final String CONFIRM_PWD_HEADER = "X-Admin-Confirm-Pwd";

    @Resource
    private AppConfig appConfig;

    @Resource
    private PasswordService passwordService;

    /**
     * 操作者口令校验（user 模块的 Dubbo provider）。check=false：provider 不可用时为 null，
     * 由下面的回退逻辑处理（历史行为是只认全局超管口令，这里保留该路径并记日志）。
     */
    @org.apache.dubbo.config.annotation.DubboReference(check = false, timeout = 3000)
    private AdminCredentialVerifier adminCredentialVerifier;

    @Before("@annotation(com.smartlect.annotation.AdminSensitiveConfirm)")
    public void beforeSensitive() {
        HttpServletRequest request = currentRequest();
        if (request == null) {
            throw new BusinessException("请求无效");
        }
        String confirmPwd = request.getHeader(CONFIRM_PWD_HEADER);
        if (StringTools.isEmpty(confirmPwd)) {
            throw new BusinessException("敏感操作需二次确认，请输入管理员密码");
        }
        // 先按"操作者自己的口令"校验（2026-10-16 审计 L-5：此前只认全局超管口令，
        // 等于把二次确认做成"只有超管能改"）；再保留全局口令作为超管的合法路径。
        String operator = null;
        try {
            com.smartlect.entity.dto.AdminPrincipalDTO principal = AdminSecurityContext.current();
            operator = principal == null ? null : principal.getAccount();
        } catch (RuntimeException ignored) {
            operator = null;
        }
        boolean operatorMatched = false;
        if (operator != null && adminCredentialVerifier != null) {
            try {
                operatorMatched = adminCredentialVerifier.verify(operator, confirmPwd);
            } catch (RuntimeException error) {
                log.debug("操作者口令校验失败（回退全局口令）account={}：{}", operator, error.getMessage());
            }
        }
        if (!operatorMatched && !passwordService.matches(confirmPwd, appConfig.getAdminPasswordHash())) {
            throw new BusinessException("管理员密码确认失败");
        }
        if (operatorMatched) {
            log.info("敏感操作二次确认通过（操作者口令）account={}", operator);
        }
    }

    private HttpServletRequest currentRequest() {
        ServletRequestAttributes attrs = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        return attrs == null ? null : attrs.getRequest();
    }
}
