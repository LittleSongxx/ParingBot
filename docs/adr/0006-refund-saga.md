# ADR-0006：退款采用持久化 Saga，退券只在整单全退

- 状态：Accepted
- 日期：2026-10-17
- 范围：order / pay / stock / coupon
- 相关代码：`backend/smartlect-order/app/src/main/java/com/smartlect/biz/RefundSagaService.java`、`backend/smartlect-order/app/src/main/java/com/smartlect/biz/RefundSagaTransactionService.java`、`backend/smartlect-coupon/app/src/main/java/com/smartlect/component/RefundCouponReturnListener.java`

## 背景

退款不是一次支付渠道调用：它要确认支付、恢复库存、决定是否退券、更新订单与明细状态。任一步失败都不能让整笔退款丢失；用户也可能只退一张订单里的某一件商品。项目需要可恢复、可审计、可人工介入的退款流程。

## 决策

1. **按明细退款**：`refund_request` 唯一键是 `order_item_id`，不是 `order_id`；支持部分退款，累计 `refunded_amount`，按剩余 NORMAL 明细数决定订单聚合状态。
2. **持久化状态**：`PENDING_PAYMENT → PAYMENT_CONFIRMED → STOCK_PENDING → COMPLETED`，旁路 `MANUAL_REVIEW / REJECTED`。状态落库，进程重启后可续跑。
3. **支付步**：先 CAS 抢支付租约，再调渠道退款；失败按 `refund.saga.retry-seconds` / `max-retries` 重试，耗尽转人工。
4. **库存步**：一个本地事务内翻明细、累计金额、算订单聚合状态、置 `STOCK_PENDING`、写 `refund-stock` Outbox；库存服务用 `refundRequestId` 做幂等键回补，成功后回发 `refund-result`。
5. **退券步**：只有整单全退且没有剩余 NORMAL 明细，才写 `refund-coupon-return` Outbox；券消费端做 USED→NOUSE 条件更新。部分退款不退券。
6. **人工复核**：管理端 approve 按 `review_origin_status` 回到原阶段，reject 置 `REJECTED`；`refundSagaReconcile` 定时续跑。

## 备选方案

- **一次同步 RPC 完成退款**：失败无法恢复，不采用。
- **TCC**：资金/库存强一致更稳，但需要 Try/Confirm/Cancel 和空回滚/悬挂处理；当前规模用持久化 Saga + 重试/人工。
- **工作流引擎**：可视化好，但引入额外中间件和运维；当前状态机足够。
- **整单退款**：实现简单，但无法支持“只退一件”，不符合电商售后。

## 后果

**正向**

- 退款可恢复、可审计、可人工接管；不会因为一次网络失败丢掉退款。
- 部分退款、整单退款、退券规则边界清晰。
- 支付/库存/券各自幂等，重复消息不会双退/双加库存。

**代价**

- 存在中间态：订单可能已 REFUNDED，但库存仍在 STOCK_PENDING；前端/客服要能解释。
- 需要维护 Saga 状态、重试、人工复核、对账四套逻辑。
- 部分退款不退券，规则需要在产品/文档中明确。

## 何时重审

- 售后流程增加到换货/维修/多包裹/多仓；
- 需要资金级退款账本/三方对账；
- 退款量大到需要独立售后平台/工作流引擎。

## 证据

- 状态：`RefundSagaStatus`。
- 主流程：`RefundSagaService#requestRefund/processPayment/queueStockRestore`。
- 库存回补：`RefundStockListener`、`SkuStockService#restoreRefundStock`。
- 退券：`RefundCouponReturnListener`、`CouponInternalService#returnCouponForRefund`。
- 测试：`RefundSagaServiceTest`、`RefundSagaTransactionServiceTest`、`RefundCouponReturnHookTest`、`PayChannel4MockIT`。
