# ADR-0003：库存扣减采用条件更新 + 变更账本

- 状态：Accepted
- 日期：2026-10-17
- 范围：stock
- 相关代码：`backend/smartlect-stock/app/src/main/java/com/smartlect/biz/SkuStockService.java`、`backend/smartlect-stock/app/src/main/resources/com/smartlect/mappers/SkuStockMapper.xml`、`backend/smartlect-stock/app/src/main/java/com/smartlect/mappers/StockChangeRecordMapper.java`

## 背景

库存是交易事实，不能先查后改：两个并发请求都读到 1、都认为够、都去扣，会超卖。项目也没有引入 Redis 预扣作为默认路径；库存表是唯一事实源，商品缓存里的 `stock` 只是展示字段。

## 决策

1. 用一条带条件的 UPDATE 完成“判断 + 扣减”：
   ```sql
   UPDATE sku_stock
   SET stock = stock + #{changeAmount}
   WHERE product_id = ?
     AND property_value_id_hash = ?
     AND stock + #{changeAmount} >= 0
   ```
   影响行数为 0 即库存不足，不先 `SELECT` 再判断。
2. 批量扣减先按 SKU 合并数量、按 key 排序，再逐条更新；任一失败抛异常回滚整个本地事务，排序降低交叉死锁概率。
3. 用 `stock_change_record` 做只增不删的变更账本，业务键就是主键：
   - 下单扣减：`order-deduct:{payOrderId}`，类型 `ORDER_DEDUCT`；
   - 关单回补：`order-close:{payOrderId}:{skuHash}`，类型 `ORDER_RESTORE`；
   - 退款回补：`refundRequestId`，类型 `REFUND_RESTORE`。
4. 回补前先确认扣减账本存在，避免“从未扣减过”的订单虚增库存；重复消息靠 `INSERT IGNORE` 挡住。

## 备选方案

- **悲观锁 `SELECT ... FOR UPDATE`**：强一致，但并发下串行、易死锁，当前未使用。
- **版本号乐观锁**：需要额外 version 字段和重试；条件更新已经能表达“库存足够才扣”，不需要版本。
- **Redis 预扣**：高并发更合适，但会引入缓存-DB 一致性和少卖/超卖边界；当前默认不用，原型见 ADR-0010。
- **预占/TCC**：适合下单即锁库存的高价值场景；当前是下单扣减 + 超时回补，见 ADR-0002。

## 后果

**正向**

- 正确性由单条 UPDATE 的行锁保证，不依赖应用层锁。
- 账本可审计、可重放，重复扣减/回补有确定结果。
- 库存不足、重复请求、关单回补三条路径都能单独测试。

**代价**

- 热点 SKU 的单行行锁会成为瓶颈；大促/直播需要 Redis 预扣、分桶或预占。
- 账本只增不删，需要归档/清理策略。
- 影响 0 行可能有多种含义（库存不足、已处理、SKU 不存在），调用方必须结合上下文解释。

## 何时重审

- 单个 SKU 的并发扣减达到数据库行锁瓶颈；
- 需要多仓/共享库存/预占释放；
- 需要跨区域库存单元化。

## 证据

- SQL：`SkuStockMapper.xml#changeStock`。
- 扣减/回补/幂等：`SkuStockService#changeStockBatch`、`restoreOrderStock`、`restoreRefundStock`。
- 测试：`SkuStockServiceTest`、`MiddlewareIT`、`TransactionPersistenceIT`。
- 订单侧业务键：`OrderCreationService` 的 `order-deduct:` 与补偿路径。
