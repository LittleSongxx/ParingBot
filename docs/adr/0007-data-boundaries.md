# ADR-0007：每服务一个 schema，读模型与交易事实分离

- 状态：Accepted
- 日期：2026-10-17
- 范围：product / stock / cart / order / pay / coupon / user / admin
- 相关代码：`backend/smartlect-product/app/src/main/java/com/smartlect/component/ProductCacheService.java`、`backend/smartlect-product/app/src/main/java/com/smartlect/search/ProductIndexService.java`、`backend/smartlect-product/app/src/main/java/com/smartlect/component/ProductIndexConsumer.java`、各服务 `src/main/resources/db/migration/`

## 背景

项目只有一个 MySQL 实例，但订单、库存、商品、券、支付、购物车、用户、管理端各自拥有独立 schema。跨服务关联只靠 ID/事件，不建跨库外键；商品有缓存和 ES 读模型，库存是交易事实，不能混在一起。

## 决策

1. **每服务独立 schema**：服务只写自己的库；跨服务通过 Dubbo/内部 HTTP/MQ 读取，不直接查别人的表。
2. **商品缓存不存库存**：详情缓存保存 SPU/属性/SKU 价格，写入前把 SKU `stock` 清零；命中后用库存 RPC 实时补齐。库存永远以 `sku_stock` 为准。
3. **搜索是独立读模型**：Canal 订阅 `smartlect_product.*`，经 RocketMQ 投递到 `ProductIndexConsumer`，更新 ES 索引并失效商品缓存；写路径不双写 ES。
4. **管理端不复制领域数据**：`admin` 通过 Dubbo 聚合订单/用户/商品/库存，本地只保存统计、补偿日志、Demo 场景；跨库分析用 `SQL SECURITY DEFINER` 视图。
5. **无跨库外键**：逻辑关联列（`pay_order_id`、`order_item_id` 等）有索引/唯一键，但数据库不替服务保证父行存在；孤儿引用由状态机、幂等账本、对账处理。
6. **商品写路径在域内收口**：SKU 指纹由服务端重算；上下架/删除用旧状态做条件更新，状态变化后失效详情缓存。缓存只是读模型，不能绕过商品域的状态判断。

## 备选方案

- **单库单表/共享表**：开发快，但服务边界会被 SQL 穿透，无法独立演进。
- **每服务独立 MySQL 实例**：隔离更好，但本地演示/运维成本高；当前用一个实例 + 独立 schema。
- **写路径双写 ES**：实时性好，但会出现“库成功、ES 失败”；选择 CDC 读模型。
- **缓存库存**：读性能好，但会展示旧库存、下单再被拒；选择缓存清零 + 实时回补。

## 后果

**正向**

- 服务边界清晰，跨库关联可审计；商品读链路可以独立扩展。
- 缓存/ES 故障不会改变交易事实；库存始终可回源。
- 管理端没有第二套真相。

**代价**

- 单 MySQL 实例仍是单点；schema 隔离不等于物理隔离。
- CDC/缓存存在延迟窗口，搜索可能短暂少结果；需要索引重建/对账。
- 跨库分析依赖视图/Dubbo，复杂查询能力有限。

## 何时重审

- 单实例容量/故障域不可接受，需要分库分表/多实例；
- 搜索索引一致性要求提高，需要版本号/别名切换/全量校验；
- 管理端分析需求增长，需要独立数仓。

## 证据

- 缓存清零/回补：`ProductCacheService#put/get`、`ProductInfoServiceImpl#replenishRealtimeStock`。
- CDC：`ProductIndexConsumer`、`ProductIndexService`。
- 数据模型：各服务 `db/migration/V1__baseline.sql`。
- 已知边界：README 的“已知边界与遗留”。
