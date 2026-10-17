package com.smartlect.constants;

public final class AdminPermissions {

    public static final String ADMIN_MANAGE = "admin:manage";
    public static final String ADMIN_LEGACY = "admin:legacy";
    public static final String ADMIN_TRIAL = "admin:trial";
    public static final String ANALYTICS_READ = "analytics:read";
    public static final String ANALYTICS_EXPORT = "analytics:export";
    public static final String AUDIT_READ = "audit:read";
    // ADR-0008 权限粒度细化
    public static final String OPS_COMPENSATION_READ = "ops:compensation-read";
    public static final String OPS_TOOL = "ops:tool";
    public static final String ORDER_MANAGE = "order:manage";
    public static final String PRODUCT_MANAGE = "product:manage";
    public static final String COUPON_MANAGE = "coupon:manage";
    public static final String USER_MANAGE_READ = "user:manage-read";
    // 写侧补齐：user:manage-read 是只读，不能拿来保护禁用用户/删地址等写操作
    public static final String USER_MANAGE = "user:manage";
    public static final String SETTINGS_MANAGE = "settings:manage";
    public static final String MODERATION_MANAGE = "moderation:manage";

    public static final String SUPER_ADMIN_ROLE = "SUPER_ADMIN";
    public static final String TRIAL_OPERATOR_ROLE = "TRIAL_OPERATOR";

    private AdminPermissions() {
    }
}
