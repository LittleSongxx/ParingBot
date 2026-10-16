package com.smartlect.security;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.dto.AdminPrincipalDTO;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 展厅身份的权威判定（{@link TrialIdentities#isTrialAdmin}）：管理端守卫（写拒绝）
 * 与订单脱敏都依赖它，判定错一边就会误伤（超管被当展厅）或漏放（展厅被当超管）。
 *
 * <p>2026-10-16 实测教训：身份不能用 admin:trial 权限点判定——超管持有全部权限点。
 * 排他标识只有两个：固定账号 gallery、角色 TRIAL_OPERATOR（角色分配被
 * AdminIdentityService 的"展厅角色只能由系统种子创建"守住）。</p>
 */
class TrialAccessTest {

    private static AdminPrincipalDTO principal(String account, List<String> roles, List<String> permissions) {
        AdminPrincipalDTO dto = new AdminPrincipalDTO();
        dto.setAccount(account);
        dto.setRoles(roles);
        dto.setPermissions(permissions);
        return dto;
    }

    @Test
    void galleryAccountIsTrial() {
        assertTrue(TrialIdentities.isTrialAdmin(principal("gallery", List.of("TRIAL_OPERATOR"),
                List.of("admin:trial", "order:manage"))));
    }

    @Test
    void trialRoleAloneIsEnoughEvenIfAccountDiffers() {
        assertTrue(TrialIdentities.isTrialAdmin(principal("gallery-v2", List.of("TRIAL_OPERATOR"), List.of())));
    }

    @Test
    void superAdministratorIsNotTrial() {
        // 超管的真实权限集合 = 全部权限点（含 admin:trial）——必须豁免，否则
        // 超管的发货/改分类/改状态会被展厅守卫 403，订单收件人也会被脱敏。
        assertFalse(TrialIdentities.isTrialAdmin(principal("admin", List.of("SUPER_ADMIN"),
                List.of("admin:trial", "admin:legacy", "admin:manage", "order:manage"))));
    }

    @Test
    void legacyAdminWithoutSuperRoleIsNotTrial() {
        // 带老管理端标记（admin:legacy）的非超管账号同样不属于展厅
        assertFalse(TrialIdentities.isTrialAdmin(principal("ops", List.of("OPS"),
                List.of("admin:trial", "admin:legacy"))));
    }

    @Test
    void nullPrincipalIsNotTrial() {
        assertFalse(TrialIdentities.isTrialAdmin(null));
    }
}
