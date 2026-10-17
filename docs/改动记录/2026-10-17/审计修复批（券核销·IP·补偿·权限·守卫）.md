# 审计修复批：券核销收敛 · IP 信任链 · coupon 补偿 · 管理端权限 · 启动守卫 · 索引初始化

- 关联前次记录：同日 [收尾整理与全面复查.md](收尾整理与全面复查.md)、[后端全景讲解文档.md](后端全景讲解文档.md)。
- 性质：**代码 + 迁移 + 文档**；不改已应用的 V1–V4 迁移，不改 `order_info` schema，不部署。

## 需求

上一轮深度分析（见 [后端全景讲解文档.md](后端全景讲解文档.md) 第 18 章）列出了「值得改」的 6 项：
支付成功后券核销无收敛、C 端 IP 可伪造、退款还券消费失败无落点、管理端 12 个写接口无权限注解、
服务通配绑定 + actuator 暴露、商品索引每次启动全量重建。用户要求全部修掉，并同步讲解文档。

## 具体变更

### 1. 支付成功后的券核销/激活收敛（P0）

- `OrderPaymentService`：新增 `convergeCouponAfterPaid`，在三个「已支付/已完成」早退分支各补一次幂等收敛：
  普通单 `CANT→USED` 核销、秒杀单 `CANT→NOUSE` 激活；**排除 REFUNDED**（全额退款已把券还成 NOUSE，再核销会永久重抛）。
- 触发点：`paySuccessInLock` 全已支付分支、`paySuccessForCouponRush` 全 COMPLETED 分支、`handlePaySuccessConflict` 的全结清分支。
- 回归：`OrderPaymentServiceTest` 新增 3 例（首次核销失败→重投补核销；REFUNDED 不重核销；秒杀单补激活），原有 1 例不动，共 4 例通过。
- 关键源码：`backend/smartlect-order/app/src/main/java/com/smartlect/biz/impl/OrderPaymentService.java:124-130,234-238,288-292,332-366`

### 2. C 端 IP 信任链（P0）

- 三处旧实现（取 XFF 第一段）统一改为 `IpUtils.resolveClientIp`：`AccountController.getClientIp`、
  `admin/FileController.getClientIp`、`RateLimitAspect.getClientIp`。
- `/account/checkCode` 增加 IP 限流（60s / 30 次）——4 位数字图片验证码此前无任何限流，可 OCR。
- 新增 `IpUtilsTest`（6 例）：伪造第一段被忽略、`X-Real-IP` 优先、XFF 取最后合法段、非法值回落 `remoteAddr`、IPv6 归一化。
- 关键源码：`backend/smartlect-user/.../controller/AccountController.java:126-133,257-262`、
  `backend/smartlect-user/.../controller/admin/FileController.java:87-90`、`backend/smartlect-common/.../aspect/RateLimitAspect.java:114-118`

### 3. coupon 补偿表与消费失败自动重放（P1）

- 新增 `smartlect-coupon/.../db/migration/V3__mq_compensation_log.sql`（14 列 + 唯一键 + 3 个索引，结构与其余五库一致）。
- coupon `application.yml`：`auto-replay-enabled: true`、新增 `auto-replay-consume: true`；修正原先「matchIfMissing=true」的过时注释。
- `MqCompensationLogService` 增加三参重载；`MqCompensationAutoReplayTask` 读 `mq.compensation.auto-replay-consume`
  （默认 false），**只有打开时才重放 `exchange=mq.consume` 的消费失败**（原先无条件跳过）。
- `scripts/xxljob_setup.py`：新增 `('smartlect-coupon','mqCompensationReplay','0 * * * * ?',...)`；任务数 15→16。
- 回归：`MqCompensationLogServiceImplTest` 3 例（默认跳过消费失败、打开后重放、超重试上限跳过）；
  `MqSchedulingLockScopeTest` 同步为三参校验；`SchedulingFlagConsistencyTest` 自动校验「flag=true 必须有表」；
  `MiddlewareIT` 自动跑 coupon V3 迁移（真库）。
- 关键源码：`backend/smartlect-common/.../service/impl/MqCompensationLogServiceImpl.java:139-181`、
  `backend/smartlect-common/.../task/MqCompensationAutoReplayTask.java:34-56`

### 4. 管理端写接口补权限 + 收紧 CI 门禁（P1）

- `AdminPermissions` 新增 `user:manage`、`settings:manage`、`moderation:manage`；新增
  `smartlect-user/.../db/migration/V5__admin_write_permissions.sql`（只授 SUPER_ADMIN）。
- 19 个写方法补**方法级** `@SaCheckPermission`（全部 `orRole="SUPER_ADMIN", type="admin"`）：
  发货、禁用用户、删地址、分类 5 个写、物流设置、图片审核 3 个、文件上传、商品 6 个写。
  不用类级注解：gallery 的分类/物流**读**页面必须保持可用。
- **保留** `TrialAdminAccess` 全部条目（gallery 有 `order:manage`，删掉 delivery 条目会让展厅越权）。
- `scripts/check_admin_authz.py` 收紧：保护证明只认 `@SaCheckPermission` / `@TrialReadable`，
  不再接受「登记在展厅拒绝清单」；拒绝写接口只写 `admin:trial`。改后 32 个写接口全绿。
- 测试影响：现有控制器测试都是直接 `new Controller()` / Service 级，不经 SaInterceptor，无需改。
- 关键源码：`backend/smartlect-common/.../constants/AdminPermissions.java:17-20`、
  `backend/smartlect-{order,user,product,admin}/.../controller/admin/*.java`、`scripts/check_admin_authz.py:89-105`

### 5. 启动守卫：通配绑定 + actuator 暴露（P2）

- `ProductionSafetyValidator` 与 `GatewayProductionSafetyValidator`：生产就绪（或 prod profile）下，
  `server.address` 为空/`0.0.0.0`/`::` 且 actuator 暴露 `prometheus`/`*` → 启动失败；
  留 `smartlect.allow-wildcard-bind` 作显式逃生口。
- 集群脚本写入 `SMARTLECT_ALLOW_WILDCARD_BIND=true`（集群必须通配绑定，安全边界在安全组）；
  `deploy/cluster/README.md` 增加「安全组」核对项与公网探测命令。
- 测试：`ProductionSafetyValidatorTest` 14 例（新增 4 例）、新增 `GatewayProductionSafetyValidatorTest` 6 例。

### 6. 商品索引启动重建按差异判断（P2）

- `ProductIndexInitializer`：`ensureIndex` 后比较 ES 文档数与在售商品数；索引为空/读不到/少于在售数才重建，
  多余文档不触发。新增 `smartlect.canal.index-force-rebuild`（默认 false）供人工强制。
- 已知盲区：等量内容陈旧（Canal 漏一次 upsert、条数不变）检测不到，需要 force 开关。
- 回归：`ProductIndexInitializerTest` 7 例（不可达 / 空索引 / 缺文档 / 计数未知 / 覆盖 / 多余 / 强制）。

## 验证方式与证据

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 全仓单测 `mvn test` | **497 例，0 失败 0 错误** | 本轮命令输出（见下「命令」） |
| 集成档 `mvn -B -Pintegration verify` | **BUILD SUCCESS**（2:26）；`MiddlewareIT` 6 例通过（含 coupon V3 真库迁移）、`OutboxLeaseSqlIT` 2 例、`OrderConsistencyFixIT`/`PayChannel4MockIT` 等通过 | 日志见 `eval/verification/2026-10-17/audit-fix/integration-verify.log`（本次运行生成，见索引） |
| 管理端授权门禁 | `84 端点 / 32 写 / 33 拒 + 3 放行 → 通过`（收紧后） | 同上 |
| 覆盖率棘轮 | 汇总行覆盖 **37.2% → 39.0%**，通过；基线未抬升 | 同上 |
| 讲解文档渲染 | 4 档视口问题 0；导航 19 章 ×2 轮 **38/38 OK** | `eval/verification/2026-10-17/backend-tour-doc/{render-check.txt,nav-sync.txt}` 与 `screenshot-light-ch18.png` |

命令（本机，Docker 28.5.1）：

```bash
cd backend && mvn -q test
cd backend && mvn -B -Pintegration verify
python3 scripts/check_admin_authz.py
python3 scripts/coverage_gate.py
python3 eval/verification/2026-10-17/backend-tour-doc/render_check.py 架构图/Smartlect后端全景讲解.html 1460 1180 1000 860
python3 eval/verification/2026-10-17/backend-tour-doc/nav_sync_check.py 架构图/Smartlect后端全景讲解.html 2
```

## 启用与回滚

- **coupon 补偿**：V3 迁移随启动自动应用（Flyway）；回滚 = 把 `mq.compensation.auto-replay-enabled` 设回 false
  （任务不再注册，表保留无害）。Nacos 里若有 `smartlect-coupon.yml` 覆盖，需 `python3 scripts/nacos_config_push.py smartlect-coupon` 后重启。
- **权限**：V5 只新增权限码并授超管，回滚应用版本即可；已授的数据保留不影响旧代码。
- **启动守卫**：只影响 `production-ready=true`/prod profile；普通部署无行为变化。
- **索引初始化**：`index-force-rebuild=true` 可恢复"每次启动全量重建"的旧行为。
- **券收敛**：无开关，随版本生效；逻辑是幂等补动作，重复执行安全。

## 未完成项 / 未知

- 覆盖率基线未用 `--update` 抬升（37.2% → 39.0%），留给发布流程决定。
- coupon 的补偿行在管理端看不到（`MqCompensationLogController` 只读 admin 自己的库）；本次只做了自动重放，
  没做跨库查看/手工重放入口。
- 商品详情仍不校验上下架、`order_info` 三列假金额、批量库存账本信息有损、`ALLOWED_WRITE_PATTERNS` 运行时不起作用：
  按计划**本轮不改**，理由见讲解文档第 18 章「三、仍然存在的接缝」。
- **未部署**：本轮只改仓库工作区；集群安全组是否真的封住 18080-18108 仍需从公网探测确认。

## 关联代码版本

- 起始提交 `e5bfdd3`；本轮全部为未提交工作区改动（代码 31 个文件 + 3 个新测试/迁移文件 + 文档）。
