# ADR-0010：热点库存原型默认关闭，DB 仍是事实源

- 状态：Accepted（原型已实现，默认关闭）
- 日期：2026-10-17
- 范围：stock
- 相关代码：`backend/smartlect-stock/app/src/main/java/com/smartlect/component/HotSkuStockGate.java`、`backend/smartlect-stock/app/src/main/java/com/smartlect/biz/SkuStockService.java`、`backend/smartlect-stock/app/src/main/java/com/smartlect/task/HotSkuStockReconcileTask.java`、`backend/smartlect-stock/app/src/main/resources/lua/`

## 背景

默认库存路径是数据库条件更新 + 变更账本，正确、简单，但热点 SKU 的单行行锁会成为瓶颈。公开的大厂实践通常会在数据库前加一层 Redis/Lua 预扣、库存分桶或预占；项目是单店演示，不需要真的扛大促，但需要把这条演进路线和代价讲清楚，并保留一个可验证的原型。

## 决策

1. **DB 仍是事实源**：`sku_stock` + `stock_change_record` 始终是最终裁决；Redis 只做前置闸门，不替代 DB。
2. **默认关闭**：`smartlect.stock.hot-path.enabled=false`；只对配置的 SKU 生效，不影响普通商品。
3. **原型能力**：
   - 按桶拆分可售库存，Lua 按桶顺序原子扣减；桶总量不足时整单拒绝，不做部分扣减。
   - 预留标记 key 含 `payOrderId + sku`，TTL 防悬挂；同一业务键只预留一次。
   - Redis 预留成功 → DB 条件更新；DB 失败立即释放；关单/退款 DB 回补后再回补 Redis。
   - 对账任务比较桶和 vs DB；差异写指标/日志；只在无活跃预留时按 DB 重置 Redis，避免自动超卖。
4. **失败方向**：宁可少卖，不可超卖；Redis 不可用时回退 DB 路径（fail-open 到 DB），不阻塞下单。
5. **不默认启用**：只有经过测试、基准和故障演练后，才允许在特定 SKU/活动上打开。

## 备选方案

- **纯 Redis 扣减**：性能最高，但缓存-DB 一致性/少卖风险大；不采用。
- **数据库分桶**：把一行拆 N 行，提升并发；会引入跨桶借还和“有库存预占不到”；当前不做。
- **TCC/预占**：强一致、适合高价值库存；复杂度高，当前不做。
- **直接上 Redis 集群/分片**：单店规模不需要；原型只用单 Redis。

## 后果

**正向**

- 在不改变默认交易路径的前提下，验证热点库存的演进方向。
- 有明确的开关、对账和失败回退，不会悄悄影响普通商品。
- 为后续分桶/预占/单元化留下接口和文档。

**代价**

- 原型增加 Redis 依赖、Lua 脚本、预留 TTL、对账任务；复杂度和故障面上升。
- 桶不跨借会少卖；对账/重置需要谨慎，避免把已预留库存覆盖。
- 不是生产级高并发库存系统；真实大促仍需压测、容量规划和多级降级。

## 何时重审

- 热点 SKU 的 DB 行锁成为真实瓶颈；
- 需要多仓/共享库存/预占释放；
- 需要跨区域库存单元化。

## 证据

- 默认路径：`SkuStockService#changeStockBatch`、`SkuStockMapper.xml#changeStock`。
- 原型：`HotSkuStockGate` + `lua/hot_stock_reserve_v1.lua` / `hot_stock_release_v1.lua` + `HotSkuStockReconcileTask`。
- 测试：`HotSkuStockGateIT`（Testcontainers Redis）覆盖预占/幂等/不足不落桶/释放/对账；`SkuStockServiceTest` 覆盖 DB 失败释放；关闭开关时行为不变。
- 基准：订单链路 10/20 VUs，flag off/on 各一轮；结果与口径见 `docs/verification/order-load.md`。
