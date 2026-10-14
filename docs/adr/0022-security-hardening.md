# ADR-0022：安全加固——登录锁定、邮箱枚举缓解、管理端权限粒度、生产校验器强化、SKU 指纹服务端化

- 日期：2026-10-14；状态：已接受（批次五实施）；关联 ADR-0011（Sa-Token 迁移）

## 决定

1. **用户登录失败锁定**：UserLoginLockService（邮箱+IP 双维度，5 次/15 分钟，同 AdminLoginLockService 模式），
   接入 login 三点（前置 ensureNotLocked / 失败 recordFailure / 成功 clearFailures）。
2. **邮箱枚举缓解**（行为变更）：注册重复改"注册失败：请检查输入或稍后重试"、找回密码改
   "如该邮箱已注册，重置邮件已发送"——不再暴露账号存在性。
3. **管理端权限粒度**：user V4 新增 6 权限点（ops:compensation-read / ops:tool / order:manage /
   product:manage / coupon:manage / user:manage-read，SUPER_ADMIN 全量），六个高危管理类挂
   类级 @SaCheckPermission(orRole=SUPER_ADMIN)：Tool（延迟队列写）、MqCompensationLog、
   StatisticsInfo（analytics:read）、UserInfo、DiscountCoupon、RefundReview。gallery
   （TRIAL_OPERATOR）不获新权限点，原能力不变。
4. **ProductionSafetyValidator 强化**：prod/production profile 自动启用（忘设开关不再裸奔）；
   令牌弱值检查升级为长度 ≥24；yml 去掉 trial 密码明文默认（空值回退 TrialIdentities 公布演示值，
   演示行为不变）。
5. **SKU 指纹服务端化**：saveProduct 以 md5(propertyValueIds) 重算覆写 hash 并拒绝重复组合
   （此前前端提交、后端不校验）。商品上下架/删除改条件更新（CAS），并发不再越权覆盖。
6. **Sa-Token 裸键读可观测**：getAdminPrincipal 解析失败由静默 null 改 warn 留痕。
   服务端 4 处裸键调用点保持现状（由 RedisComponentSaTokenSessionTest 契约测试钉住键布局兼容），
   完全收敛到 StpUtil API 列为后续演进——显式偏离记录于此。

## 验证

UserLoginLockServiceTest（4 例）、SkuHashNormalizationTest（3 例）、ProductionSafetyValidatorTest
增 prod-profile 自动启用/短令牌拒绝 2 例；全量 mvn test 绿。

## 配置/回滚

新增键 smartlect:user:login:*（TTL 15 分钟自动过期，无需清理）；user V4 前向迁移（权限种子幂等，
回滚代码即恢复仅登录级校验）；yml trial 密码默认值变更——线上若依赖旧默认行为需显式设
SMARTLECT_TRIAL_PASSWORD（演示值回退兜底，无实际影响）。
