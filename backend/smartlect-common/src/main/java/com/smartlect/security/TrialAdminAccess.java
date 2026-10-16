package com.smartlect.security;

import com.smartlect.constants.AdminPermissions;
import org.springframework.util.AntPathMatcher;

import java.util.List;

/**
 * 演示管理员（TRIAL_OPERATOR / gallery）的服务端策略。
 *
 * <p><b>为什么需要它</b>：管理端此前只有"登录校验 + 注解校验"，<b>没注解等于无需权限</b>——
 * 展厅账号（口令公开在 README）因此可以直接调 `/admin/order/delivery`（发货）、
 * `/admin/sysCategory/saveCategory`（改分类树）、`/admin/user/changeStatus`（封禁用户）等
 * 只靠"前端菜单隐藏"保护的接口。实测（2026-10-16）确认请求能进到业务逻辑。</p>
 *
 * <p><b>策略（与助手侧 admin API 的口径一致：读 require_any(admin:trial)、写 require(admin:legacy)）</b></p>
 * <ul>
 *   <li>读（GET 或读语义的 POST）：默认允许，命中 {@link #DENIED_PATH_PATTERNS} 的隐私面除外；</li>
 *   <li>写（POST/PUT/PATCH/DELETE）：默认拒绝，只有 {@link #ALLOWED_WRITE_PATTERNS} 显式放行
 *       （退款复核是产品上明确给展厅保留的能力，见 README 允许清单）；</li>
 *   <li>{@link TrialReadable} 注解可在方法级显式放宽（也是该注解第一次有了消费者）。</li>
 * </ul>
 *
 * <p>静态覆盖由 {@code scripts/check_admin_authz.py} 在 CI 里把关：新增管理端写接口若既无
 * 权限注解、又不在本清单的语义内，门禁直接红。</p>
 */
public final class TrialAdminAccess {

    /** 展厅身份标识：角色码或权限点任一命中即视为 trial（与前端 TRIAL_MENU_PATHS 同一套身份）。 */
    public static final String TRIAL_ROLE = "TRIAL_OPERATOR";
    public static final String TRIAL_PERMISSION = "admin:trial";

    /** 拒绝文案与前端常量保持一致（web/admin/src/constants/trial.js 的 TRIAL_ADMIN_DENIED）。 */
    public static final String DENIED_MESSAGE =
            "作品集展厅账号只能查看看板、商品、订单和知识库，不能改库存、发知识、发券或查看用户隐私。";

    /**
     * 写操作白名单：产品上明确允许展厅使用的写能力。
     * 目前只有退款复核（README「能做什么」列了退款复核）——新增放行必须同时改这里与门禁脚本。
     */
    public static final List<String> ALLOWED_WRITE_PATTERNS = List.of(
            "/admin/refundReview/approve",
            "/admin/refundReview/reject",
            "/admin/account/logout");

    /**
     * 拒绝清单：**用户隐私读取面 + 全部写接口**（写接口逐条列名，因为管理端读接口也是 POST，
     * 无法用 HTTP 方法区分读写）。清单完整性由 {@code scripts/check_admin_authz.py} 在 CI 里强制：
     * 新增写接口若既不在本清单、又无权限注解/二次确认，门禁直接红。
     *
     * <p>订单域收件人隐私走脱敏（{@link TrialOrderPrivacy}）而不是拒绝，页面功能不受影响。</p>
     */
    // 注：物流读取面（/admin/order/getLogistics 与 /admin/orderLogisticsInfo/**）不在此清单——
    // 它们允许读取，但收发件人 PII 由 TrialOrderPrivacy 脱敏（订单页需要物流进度）。
    public static final List<String> DENIED_PATH_PATTERNS = List.of(
            // —— 隐私读取面（ README：不能查看用户隐私）——
            "/admin/user/**",
            "/admin/userInfo/**",
            "/admin/userAddress/**",
            "/admin/productCart/**",
            "/admin/imageModeration/**",
            // —— 运维面（第二道；本来也要求 ops:* 权限）——
            "/admin/mqCompensationLog/**",
            "/admin/tool/**",
            // —— 写接口逐条列名 ——
            "/admin/productInfo/addProduct",
            "/admin/productInfo/updateProduct",
            "/admin/productInfo/updateSkuStock",
            "/admin/productInfo/updateProductStatus",
            "/admin/productInfo/deleteProduct",
            "/admin/productInfo/commendProduct",
            "/admin/sysCategory/saveCategory",
            "/admin/sysCategory/delCategory",
            "/admin/sysCategory/changeCategorySort",
            "/admin/sysCategory/saveProductProperty",
            "/admin/sysCategory/delProductProperty",
            "/admin/order/delivery",
            "/admin/setting/saveLogistics",
            "/admin/user/changeStatus",
            "/admin/imageModeration/handleReview",
            "/admin/imageModeration/unbanUser",
            "/admin/imageModeration/censorImage",
            "/admin/userAddress/deleteUserAddressByAddressId",
            "/admin/file/uploadImage",
            "/admin/discountCoupon/saveDiscountCoupon",
            "/admin/discountCoupon/updateDiscountCouponStatus",
            "/admin/discountCoupon/warmupRushStock",
            "/admin/discountCoupon/reconcileRushStock",
            "/admin/mqCompensationLog/updateStatus",
            "/admin/mqCompensationLog/replay",
            "/admin/tool/addAllOrderToDelayQueue");

    private static final AntPathMatcher MATCHER = new AntPathMatcher();

    private TrialAdminAccess() {
    }

    public static boolean isTrial(java.util.Collection<String> roles,
                                  java.util.Collection<String> permissions) {
        // 身份判定必须带超管豁免：超管拥有全部权限点（含 admin:trial），只看
        // "有 admin:trial"会把超管误判成展厅——2026-10-16 本地实测超管写券被
        // 403"展厅账号"文案拦截。口径与 TrialIdentities.isTrialAdmin 一致
        // （admin:trial 且无 admin:legacy、非 SUPER_ADMIN）。
        boolean trial = (roles != null && roles.contains(TRIAL_ROLE))
                || (permissions != null && permissions.contains(TRIAL_PERMISSION));
        boolean superAdmin = (roles != null && roles.contains(AdminPermissions.SUPER_ADMIN_ROLE))
                || (permissions != null && permissions.contains(AdminPermissions.ADMIN_LEGACY));
        return trial && !superAdmin;
    }

    /** 写方法判定：GET 视为读；其余方法一律先按写处理（真正的读语义由 ALLOWED_WRITE 之外的白名单兜底）。 */
    public static boolean isWriteMethod(String httpMethod) {
        return httpMethod != null && !"GET".equalsIgnoreCase(httpMethod);
    }

    public static boolean matchesAny(List<String> patterns, String path) {
        if (path == null || path.isEmpty()) {
            return false;
        }
        for (String pattern : patterns) {
            if (MATCHER.match(pattern, path)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 判定展厅账号能否访问该请求：命中拒绝清单即拒；否则放行。
     *
     * <p>注意"读默认放行"的代价：读接口也可能有副作用（历史上就有把写逻辑挂在 POST 读名下的例子），
     * 所以运维/隐私面同样进了拒绝清单，且清单完整性有 CI 门禁兜底。</p>
     *
     * @param path 服务内路径（不含 context-path），如 {@code /admin/order/delivery}
     * @return true = 放行；false = 拒绝（调用方返回 403 并带 {@link #DENIED_MESSAGE}）
     */
    public static boolean allows(String path) {
        if (matchesAny(DENIED_PATH_PATTERNS, path)) {
            return false;
        }
        return true;
    }

    /** 供门禁脚本与测试使用：该路径是否在"写能力"语义内（拒绝清单里的写条目 + 白名单）。 */
    public static boolean isGuardedWriteOrAllowlisted(String path) {
        return matchesAny(DENIED_PATH_PATTERNS, path) || matchesAny(ALLOWED_WRITE_PATTERNS, path);
    }
}
