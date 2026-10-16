package com.smartlect.security;

/**
 * 校验「管理端操作者自己的口令」——供敏感操作二次确认使用。
 *
 * <p>背景（2026-10-16 审计 L-5）：管理端敏感操作的二次确认此前只比对**全局超管口令**
 * （`appConfig.getAdminPasswordHash()`），操作者即使有自己的账号也过不去，等于把
 * "二次确认"做成了"只有超管能改"。本接口把校验下移到持有 `admin_account` 表的服务
 * （user 模块提供 Dubbo 实现），aspect 侧优先用操作者口令、保留全局口令作为超管的合法路径。</p>
 *
 * <p>接口定义在 common：Dubbo 契约可以来自公共模块，provider 在 user 模块实现，
 * consumer（aspect）在各服务内使用；`dubbo.consumer.check=false` 已配置，provider 缺失时
 * 返回 null 由调用方回退。</p>
 */
public interface AdminCredentialVerifier {

    /**
     * @param account     操作者账号（来自会话 principal）
     * @param rawPassword 本次请求头里带的明文口令
     * @return true = 该账号存在且口令匹配；账号不存在或 provider 不可用返回 false
     */
    boolean verify(String account, String rawPassword);
}
