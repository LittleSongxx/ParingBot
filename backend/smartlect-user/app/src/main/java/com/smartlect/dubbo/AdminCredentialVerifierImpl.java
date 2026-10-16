package com.smartlect.dubbo;

import com.smartlect.security.AdminCredentialVerifier;
import com.smartlect.service.PasswordService;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.apache.dubbo.config.annotation.DubboService;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 敏感操作二次确认的操作者口令校验（实现见接口注释）：只有 user 模块持有 admin_account 表。
 */
@Slf4j
@DubboService
public class AdminCredentialVerifierImpl implements AdminCredentialVerifier {

    @Resource
    private JdbcTemplate jdbcTemplate;
    @Resource
    private PasswordService passwordService;

    @Override
    public boolean verify(String account, String rawPassword) {
        if (account == null || account.isBlank() || rawPassword == null || rawPassword.isEmpty()) {
            return false;
        }
        String stored;
        try {
            stored = jdbcTemplate.query(
                    "SELECT password_hash FROM admin_account WHERE account = ? AND status = 1",
                    rs -> rs.next() ? rs.getString(1) : null, account);
        } catch (RuntimeException error) {
            log.warn("查询管理账号失败 account={}：{}", account, error.getMessage());
            return false;
        }
        return stored != null && passwordService.matches(rawPassword, stored);
    }
}
