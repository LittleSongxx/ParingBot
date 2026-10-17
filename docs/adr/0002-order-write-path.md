# ADR-0002：订单写路径采用五阶段与短本地事务

- 状态：Accepted
- 日期：2026-10-17
- 范围：order
- 相关代码：`backend/smartlect-order/app/src/main/java/com/smartlect/biz/impl/OrderCreationService.java`、`backend/smartlect-order/app/src/main/java/com/smartlect/biz/OrderRequestIdempotencyService.java`、`backend/smartlect-order/app/src/main/java/com/smartlect/biz/OrderQuoteService.java`

## 背景

下单要在一次请求里完成地址读取、商品快照、券锁定、订单落库、库存扣减、购物车清理、支付意图创建。如果把这些都包在一个 `@Transactional` 方法里，远程调用期间会一直占用数据库连接；项目压测曾出现单连接被占用 18.1 秒、连接池被抽干，连带支付成功处理和 Outbox 投递失败。另一方面，订单落库后如果远程步骤失败，不能简单回滚整笔订单，否则会留下无支付意图的孤儿单。

## 决策

把下单拆成五个阶段，只有第三阶段在本地事务里：

1. **读准备**：校验支付方式/来源，读地址、商品快照、SKU 在售/限购、库存预检；生成 `orderId` 与统一 `payOrderId`。只读，不占本地事务。
2. **锁远程资源**：券 `validateAndLock`（NOUSE→CANT），计算折扣并分摊。远程服务各自事务。
3. **短本地事务**：插券关系、订单、明细、物流；给每张子单写幂等键；为每张子单写 15 分钟超时关单 Outbox。只做本库写入，毫秒级。
4. **事务外远程写**：扣库存（`order-deduct:{payOrderId}`）、删购物车、创建支付意图、尽力取支付表单。每一步都必须幂等。
5. **补偿**：任一 P4 失败，回补库存（`restoreOrderStock`）、把券从 CANT 改回 NOUSE；补偿失败落 `RemoteCompensateRecorder`。

V2 报价路径采用 **claim-first**：先在短事务内占用报价，再建单；并发重复请求在占用处被 409 挡下，不先落单再发现冲突。

## 备选方案

- **一个大事务包住全部**：连接占用和回滚边界都不可控；已用压测否决。
- **先建单再同步 RPC 扣库存/建支付**：就是当前方案；区别在于远程调用必须幂等并可补偿。
- **TCC/预占**：在高价值/大促场景更稳，但需要 Try/Confirm/Cancel 和预占库存；当前单店规模不引入，热点库存另见 ADR-0010。
- **异步订单管道**：把下单请求写入队列，由消费者分阶段执行；吞吐更好，但交互语义和运维复杂度更高，当前不需要。

## 后果

**正向**

- 本地事务只覆盖本库，数据库连接不会被远程调用长期占用。
- 订单落库即真实存在；P4 失败由补偿和超时关单收敛，不会出现永久孤儿单。
- 五阶段边界清晰，每个阶段可以单独测试和重放。

**代价**

- P4 失败时订单仍存在，用户可能看到一张待付款/已关闭订单；前端要能解释。
- 需要幂等账本、Outbox、补偿记录三套机制同时正确。
- P4 是同步串行调用，请求延迟受库存/支付服务影响；高并发下需要异步化或预占。

## 何时重审

- 下单 P99 受远程调用拖累，且短事务已不是瓶颈；
- 业务要求下单即锁定库存/名额，不能接受超时回补；
- 订单量增长到需要独立订单管道/分库分表。

## 证据

- 五阶段实现：`OrderCreationService#createOrder` 与 Phase 注释。
- 幂等：`OrderRequestIdempotencyService`（指纹、PROCESSING/COMPLETED/FAILED/INCONCLUSIVE）。
- 报价：`OrderQuoteService`（`order_quote`、claim/release）。
- 压测前后：`eval/verification/cluster-loadtest-20261005/early-rig-limited/` 与 `eval/verification/cluster-tuning-20261006/`。
