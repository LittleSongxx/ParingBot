-- 管理端权限粒度细化（ADR-0022）：此前除管理员治理外全部端点仅登录级校验——
-- 高危运维工具（延迟队列写）、退款审核、发券、用户隐私、统计与 MQ 补偿日志均无权限点。
-- 新增 6 个权限点并授给 SUPER_ADMIN；TRIAL_OPERATOR（gallery 演示账号）保持原能力不变
-- （本迁移不给它新增任何权限，其现有 admin:trial 语义不受影响）。

insert into admin_permission (permission_code, description) values
    ('ops:compensation-read', 'MQ 补偿与 Outbox 运维数据读取'),
    ('ops:tool', '高危运维工具（延迟队列等写操作）'),
    ('order:manage', '订单与退款审核管理'),
    ('product:manage', '商品与 SKU 管理'),
    ('coupon:manage', '优惠券模板与发放管理'),
    ('user:manage-read', '用户信息只读管理') as incoming
on duplicate key update description = incoming.description;

insert ignore into admin_role_permission (role_id, permission_id)
select r.role_id, p.permission_id from admin_role r join admin_permission p
where r.role_code = 'SUPER_ADMIN';

-- 自查修复（2026-10-15）：README 演示契约中 gallery（TRIAL_OPERATOR）具备"退款复核"能力，
-- RefundReviewController 挂了 order:manage 后需为该角色补授，避免演示账号被 403。
insert ignore into admin_role_permission (role_id, permission_id)
select r.role_id, p.permission_id from admin_role r join admin_permission p
  on p.permission_code = 'order:manage'
where r.role_code = 'TRIAL_OPERATOR';
