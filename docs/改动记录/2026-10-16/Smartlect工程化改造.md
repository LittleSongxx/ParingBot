# Smartlect 校招工程化改造：降噪 / 真 bug / 门禁 / 结构性重构（P0+P1）

> 目的：把"设计上应该"变成"我实测过"，并把面试官一眼能看出前后不一致的部分清掉。
> 交叉引用：[全链路图解站](../../../教程/Smartlect全链路图解.html) 已在同日下线（见"产物下线"一节），本文件是本次改造的唯一记录。

## 需求与判据

需求（2026-10-16 用户提出）：允许大幅重构，删除没有必要或过于炫技的设计、重新设计部分实现以对齐行业主流做法；
文档面收敛（用户已先自行删除 `docs/**/*.md` 共 127 个跟踪文件，明确"不恢复"）；投递方向以 **Java 后端为主**；力度 **P0+P1**；三套重叠图解产物与过时架构稿**全部删除**。

每条动作必须满足其一：① 消除"前后不一致"；② 把设计变成有代码+测试+数据的实证；③ 删掉与数据量/团队规模不匹配的复杂度。不引入新中间件，不做分库分表。

## 具体变更（9 个提交）

| 提交 | 内容 |
| --- | --- |
| `36f6d98` | **产物下线**：删 `架构图/`（13 张 Archify 图 + 生成器）、`教程/Java电商后端图解/`、`教程/Smartlect全链路图解.html`、`docs/java-backend-architecture.{html,json,png}`、`figures/` 全部；未跟踪产物先备份到 `~/smartlect-archive-20261016/`（该备份已于 2026-10-17 收尾整理时清理，见当日记录） |
| `75274a9` | **P0-1 死物清理**：`smartlect.feign.*`（9 个 yml）、`alipay.*` 与 alipay-sdk 依赖、3 处空 `security:` 键、8 个 `@EnableScheduling`（全仓 `@Scheduled` 为 0）、按错误文案吞异常的死分支、空包 `api/feign/`、两个 RabbitMQ 时代死脚本、**无消费者的 LiteLLM 容器**（compose 由 12 → 11 service，默认起 10） |
| `9f62a93` | **P0-2 命名统一**：`*FeignSupport → *RpcSupport`（7 个 api 模块 + 字段 + 内部接口，43 文件 / 348 引用）、`RabbitMQ*ListenerComponent → RocketMq*Listener`、`SMARTLECT_GROWTH_* → SMARTLECT_ASSISTANT_*`（20 文件，库名保留历史命名并注释）；`runtime.py` 删掉 GROWTH 端口特判 |
| `af6efa0` | **P0-3 真 bug**：商品详情缓存库存隔离（详见下"关键缺陷一"）；新增 `ProductCacheStockIsolationTest`（5 例） |
| `e1c6d87` | **P0-5 指标**：`SmartlectMetrics` 单一出口 + 缓存 L1/L2/DB、线程池、下单/幂等重放/冲突/库存不足/Outbox sent-failed-parked/补偿重放；README 出指标字典 |
| `78f49e6` | **P0-4 门禁**：CI backend 档由 `mvn test` 升级为 `-Pintegration verify`（7 个真库 IT 进 CI）+ jacoco 覆盖率地板 + `scripts/coverage_gate.py` 棘轮（±1pp，基线 36.4%→37.0%）+ 报告 artifact；修 `OutboxLeaseSqlIT` 因 MySQL 秒级 DATETIME 四舍五入导致的抖动 |
| `ac700e9` | **P0-6 文档面**：README 重建为唯一入口（清 12 处死链、口径统一为 10 容器 / 10 任务 / 模型 ≤8、新增"指标与观测""关键决策""已知边界与遗留"三节）；架构图重绘为现役栈（Dubbo / RocketMQ / 无 Seata）并重渲染 PNG |
| `b8948dc` | **P1-1 商品检索**：加 `smartlect.search.mode`（默认 substring）+ 真实索引 A/B（详见"关键量化二"） |
| `96ebec6` | **P1-2 MySQL 纵深**：慢 SQL 拦截器（`smartlect_sql_slow_total`，只记 mapperId/SQL 骨架不记参数值）、`PageUtils` 页码上限、退款状态 N+1 → 批量、隔离级别显式化为 REPEATABLE READ + 深分页索引探针（详见"关键量化三"） |
| `3658791` | **P1-3 幂等出口**：`orderIdempotencyReconcile` 上报任务（只上报不改判）+ `scripts/reconcile_idempotency.py` 运维驱动既有核对出口；`xxljob_setup.py` 登记第 10 个任务 |
| `026080f` | **P1-4 分层**：购物车事务下移、分类保存补事务、订单内部面去掉 mapper 直连并收回 `OrderItemService`；三个 internal commerce controller 补"内部 RPC 表面"边界说明 |
| `9fd3d85` | **P1-5 故障演练**：`scripts/drills/fault_drills.py` 三件套 + 顺带定位修复 xxl-job 执行器不可达（详见"关键缺陷四"） |
| `963cf1d` | 集成档适配控制器去 mapper 直连；覆盖率基线刷新 |

## 关键缺陷与量化（可直接作为面试素材）

### 一、商品详情缓存的库存隔离（`af6efa0`）
同一根因两处表现：`put()` 在**调用方对象上**原地清零库存（冷启动首访详情返回 `stock=0`），
`get()` 把缓存实例直接交给调用方（命中路径补实时库存时污染缓存条目）。修复：入缓存的是
"副本 + 清零"，`get` 返回副本；5 例回归网锁住语义（含 Redis 故障回退为 miss）。

### 二、商品检索：不盲目改默认，先量化（`b8948dc`）
`scripts/eval_product_search.py` 对 87469 条真实索引、40 条采样、top-10 做 A/B：

| 组 | substring（现状） | hybrid（子串腿 + 分词腿） |
| --- | --- | --- |
| 逐字可命中（28 查询） | **28/28 = 100%** | 19/28 = 68% |
| 词序打乱（16 查询） | 2/16 = 12% | 7/16 = 44% |
| 宽松语义探针（6 查询） | 0 条放宽 | 前 10 条多出 15 条不逐字包含 |

机理：两腿并集看似"召回超集"，但本索引只当 ID 集过滤器用、top-N 按创建时间排序不按分数，
分词腿把命中集合从个位数放大到数百条（同查询 wildcard 1 vs match 210），宽松命中把逐字命中顶出窗口。
**结论：默认保持 substring（有实测依据）；hybrid 留作"把排序权交给 ES"那一档重构的对照。**
证据：[product-search-ab.txt](../../../eval/verification/2026-10-16/product-search-ab.txt)

### 三、深分页与索引（`96ebec6`）
`scripts/probes/page_depth_probe.sh` 在临时库灌 5 万订单实测：

| 形态 | 无二级索引 | 加 V5 索引后 |
| --- | --- | --- |
| 用户侧第 6 页 | 36.4ms，全表扫 50000 行 + filesort | 11.5ms，索引区间扫 **85 行** |
| 管理端首页（status IN(0,1)） | 51.3ms | 8.1ms（仍全表扫：低选择性过滤优化器不选索引） |
| 管理端第 2000 页 | 59.1ms | 106ms（物化 37500 行 join） |

结论：`(user_id, order_time)` 是有效索引；管理端多状态 IN 救不了；**offset 深分页的残余代价
（同形态 8.1ms vs 106ms）只能靠 keyset/两阶段分页消除**，本次只加页码上限护栏并把边界写进
`OrderInfoMapper.selectList` 注释（嵌套 LIMIT 与 PageHelper 冲突）。顺带发现：本地库 Flyway 停在 V4。
证据：[page-depth-experiment.txt](../../../eval/verification/2026-10-16/page-depth-experiment.txt)

### 四、xxl-job 兜底链路在本地整体失效（`9fd3d85`）
症状：broker 恢复后消息不自动重投；`xxl_job_log` 里所有任务只触发不执行（`handle_code=0`）。
定位链：到期消息无人重投 → 调度中心每 5s 确实在触发 → 执行器注册地址是宿主机局域网 IP，
admin 容器 `connect timed out` → 同网络实测 `host.docker.internal` 可达、该 IP 不可达。
修复三处：compose 给 admin 加 `extra_hosts: host-gateway`；`XxlJobConfig` **此前根本没有读取**
`xxl.job.executor.address`（配置无读取方 → 设了不生效），补 `setAddress`；`runtime.py` 按服务分配
固定执行器端口（10011+）并拼完整 `http://` 地址（xxl-job 对显式地址原样使用、不补端口）。
修复后实证：8 个执行器注册为 `http://host.docker.internal:10011..10018`，60 秒内
`handle_code=200` 共 17 次；drill 2 的"恢复后自动投递"由 FAIL 转 PASS。
证据：[fault-drills.txt](../../../eval/verification/2026-10-16/fault-drills.txt)

### 演练三件套的口径（`fault_drills.py`）
- **duplicate-order**：8 并发同幂等键 → 只落 1 单、库存 −1、账本 1 行 COMPLETED、
  并发窗口内 1×200 + 7×409（**无 5xx、无静默失败**）、顺序重复拿回同一单且不再扣库存；
- **mq-down**：停 broker 下单仍 200、订单独立落库、消息滞留 Outbox → 恢复后兜底任务自动投递（残留 0、无人工介入）；
- **redis-down**：会话校验 fail-closed（不再放行）、商品详情回源 DB 仍可用、恢复后原会话继续可用（AOF）。

## 关键源码

- 缓存隔离：`backend/smartlect-product/app/src/main/java/com/smartlect/component/ProductCacheService.java`
- 检索谓词开关：`.../smartlect/search/ProductIndexService.java`（类注释含实测量化结论）
- 慢 SQL：`backend/smartlect-common/src/main/java/com/smartlect/interceptor/SlowSqlInterceptor.java`
- 指标出口：`backend/smartlect-common/src/main/java/com/smartlect/metrics/SmartlectMetrics.java`
- 幂等上报任务：`backend/smartlect-order/app/src/main/java/com/smartlect/task/OrderIdempotencyReconcileTask.java`
- 执行器配置：`backend/smartlect-common/src/main/java/com/smartlect/config/XxlJobConfig.java`
- 工具：`scripts/coverage_gate.py` · `scripts/eval_product_search.py` · `scripts/probes/page_depth_probe.sh` · `scripts/drills/fault_drills.py` · `scripts/reconcile_idempotency.py`

## 验证方式与证据

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| Java 单测（10 模块） | BUILD SUCCESS | `mvn test`（每批后重跑） |
| 集成档 + 覆盖率 | BUILD SUCCESS，`All coverage checks have been met`；汇总行覆盖 36.4% → 37.0% | `mvn -Pintegration verify` + `scripts/coverage_gate.py` |
| 助手侧 | 336 tests OK（68 skip = MySQL 档） | `assistant/.venv/bin/python -m unittest discover -s assistant/tests` |
| 双前端 vitest | 31 tests passed | `scripts/dev.sh check` |
| 运行时 | 12 进程健康 + 9 Nacos 注册 + 启动冒烟通过 | `./scripts/dev.sh up` / `apps-check` |
| 故障演练 | 3/3 PASS | [fault-drills.txt](../../../eval/verification/2026-10-16/fault-drills.txt) |
| 检索 A/B | 结论：默认保持 substring | [product-search-ab.txt](../../../eval/verification/2026-10-16/product-search-ab.txt) |
| 深分页/索引 | 见上表 | [page-depth-experiment.txt](../../../eval/verification/2026-10-16/page-depth-experiment.txt) |

## 配置与数据改动（启用 / 回滚）

- `SMARTLECT_XXLJOB_EXECUTOR_HOST`（本地 bootstrap 注入 `host.docker.internal`）与按服务分配的
  执行器端口：**部署机需重新 `bootstrap` 或手动补该键后重启应用**；回滚=删该键（退回自动探测，
  但容器形态下任务会再次静默停摆）。
- `smartlect.search.mode`（默认 `substring`）：回滚=删配置项或设为 `substring`。
- `smartlect.sql.slow-threshold-ms`（默认 200）：回滚=调大或删。
- Hikari `transaction-isolation: TRANSACTION_REPEATABLE_READ`：与 MySQL 默认一致，回滚=删该行。
- 无数据库结构变更；`orderIdempotencyReconcile` 是新任务，登记脚本幂等，回滚=任务停用即可。

## 未完成项（如实记录）

1. **幂等账本自动闭环**：账本不存业务参数，`INCONCLUSIVE/MANUAL_REVIEW` 仍需运维带参数驱动核对；
   要自动闭环需在业务行冗余幂等键（列变更 + 回填），未做。
2. **深分页正解**：keyset/两阶段分页要改前端分页协议，本次只加护栏。
3. **管理端多状态列表**（`order_status IN (...)`）在 5 万行下仍全表扫 —— 需要物化/覆盖索引或改查询形态。
4. **DLedger 三副本**：仅本地编排就绪，未启用（MQ 单点）。
5. **从机 Outbox 兜底**：兜底投递只挂 order 组。
6. **Sentinel 规则热更**：代码侧完成，线上演练未做。
7. `deploy/seata/` root 属主残留目录（本地删除需 sudo，未纳入版本控制）。
8. 本地 `undo_log` 等 Seata 时代残表仍在（未做清理迁移）。

## 关联代码版本

- 本次改造前基线：`36f6d98` 之前的工作区状态（用户已删除 docs 的 127 个文件，HEAD 完好、未恢复）。
- 本次共 13 个提交（`36f6d98` … `963cf1d`），全部在 `main` 上；未推送、未重新部署线上。
- 回滚：按提交粒度 `git revert`；产物下线那笔如需恢复，除未跟踪的 `教程/Smartlect全链路图解.html`
  与 11 张截图外，其余都在 HEAD 中（该备份已于 2026-10-17 收尾整理时清理，未跟踪部分至此不可恢复）。
