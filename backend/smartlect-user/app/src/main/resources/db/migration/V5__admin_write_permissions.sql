-- 管理端写接口的权限点补齐（2026-10-17）。
--
-- 背景：V4 只给"管理员治理/退款审核/运维工具/商品/券/用户只读"加了权限点，
-- 发货、禁用用户、分类维护、物流设置、图片审核、地址删除、文件上传仍只有登录级校验。
-- 它们此前靠 TrialAdminAccess 的拒绝清单挡住公开口令的展厅账号，但 DATA_ANALYST /
-- AUDITOR 等非展厅账号可以照样调用。本次新增三个写权限点，只授 SUPER_ADMIN。
--
-- 注意：不要修改已应用的 V1–V4（Flyway checksum）；展厅（TRIAL_OPERATOR）不授新权限，
-- 其退款复核能力来自 V4 已授的 order:manage，保持不变。
insert into admin_permission (permission_code, description) values
    ('user:manage', '用户状态与收货地址管理'),
    ('settings:manage', '系统设置（发货地址等）'),
    ('moderation:manage', '图片人工复核与临时封禁处置') as incoming
on duplicate key update description = incoming.description;

insert ignore into admin_role_permission (role_id, permission_id)
select r.role_id, p.permission_id from admin_role r join admin_permission p
where r.role_code = 'SUPER_ADMIN';
