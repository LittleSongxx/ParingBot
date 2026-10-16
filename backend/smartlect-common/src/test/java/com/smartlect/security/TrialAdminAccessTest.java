package com.smartlect.security;

import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 展厅账号服务端策略：读默认允许（隐私清单除外）、写默认拒绝（退款复核显式放行）。
 *
 * <p>这组断言是"公开口令的展厅账号不能改数据"这条对外承诺的可执行版本——此前实测
 * 可以直接调 /admin/order/delivery 与 /admin/sysCategory/saveCategory。</p>
 */
class TrialAdminAccessTest {

    @Test
    void writeRequestsAreDeniedUnlessExplicitlyAllowed() {
        assertFalse(TrialAdminAccess.allows("/admin/order/delivery"), "发货必须被拒");
        assertFalse(TrialAdminAccess.allows("/admin/sysCategory/saveCategory"), "改分类必须被拒");
        assertFalse(TrialAdminAccess.allows("/admin/sysCategory/delCategory"));
        assertFalse(TrialAdminAccess.allows("/admin/productInfo/commendProduct"));
        assertFalse(TrialAdminAccess.allows("/admin/productInfo/addProduct"));
        assertFalse(TrialAdminAccess.allows("/admin/user/changeStatus"), "封禁用户必须被拒");
        assertFalse(TrialAdminAccess.allows("/admin/imageModeration/handleReview"));
        assertFalse(TrialAdminAccess.allows("/admin/setting/saveLogistics"));
        assertFalse(TrialAdminAccess.allows("/admin/file/uploadImage"));

        assertTrue(TrialAdminAccess.allows("/admin/refundReview/approve"), "退款复核是产品上保留给展厅的能力");
        assertTrue(TrialAdminAccess.allows("/admin/refundReview/reject"));
    }

    @Test
    void privacyReadsAreDeniedWhileBusinessReadsStayOpen() {
        assertFalse(TrialAdminAccess.allows("/admin/user/loadUser"), "用户档案属隐私");
        assertFalse(TrialAdminAccess.allows("/admin/userAddress/loadDataList"));
        assertFalse(TrialAdminAccess.allows("/admin/productCart/loadDataList"));
        assertFalse(TrialAdminAccess.allows("/admin/imageModeration/loadDataList"));

        assertTrue(TrialAdminAccess.allows("/admin/home/getTodayData"), "看板要能看");
        assertTrue(TrialAdminAccess.allows("/admin/order/loadOrder"), "订单列表要能看");
        assertTrue(TrialAdminAccess.allows("/admin/productInfo/loadDataList"));
        assertTrue(TrialAdminAccess.allows("/admin/sysProductProperty/loadDataList"));
    }

    @Test
    void trialIdentityIsDetectedByRoleOrPermission() {
        assertTrue(TrialAdminAccess.isTrial(Set.of("TRIAL_OPERATOR"), Set.of()));
        assertTrue(TrialAdminAccess.isTrial(Set.of(), Set.of("admin:trial")));
        assertFalse(TrialAdminAccess.isTrial(Set.of("SUPER_ADMIN"), Set.of("admin:manage")));
        assertFalse(TrialAdminAccess.isTrial(null, null));
    }
}
