# ADR-0018：交易一致性 P0 修复——孤儿订单收敛、库存恢复前置校验、对账死路径、quote claim-first 与幂等账本独立事务

- 日期：2026-10-14
- 状态：已接受（批次一实施）
- 关联：ADR-0006（移除 Seata）、ADR-0016（RocketMQ 迁移）、ADR-0017（Dubbo 迁移）
- 前置评审：全量代码评审发现 3 处已核实的高危一致性缺口与 1 处锁声明失效（详见 docs/改动记录/2026-10-14/批次一-P0交易一致性修复.md）

## 背景

四阶段代码级评审确认了以下缺陷（均为亲读源码核实）：

1. **孤儿订单窗口**：`createOrder` Phase 3 提交订单后、Phase 4 扣库存/建支付意图若失败，
   补偿只回补库存/解券，而 15 分钟超时关单消息在失败点**之后**才发送——订单永久悬置
   WAIT_PAYMENT，既无支付意图也无收敛路径。注释宣称"走补偿/超时关单收敛"与实现不符。
2. **库存虚增**：上述孤儿单（库存从未扣减成功）被手动取消或（修复 1 后）被超时关闭时，
   `restoreOrderStock` 无条件 `insertIgnore + stock+N`，回补从未扣过的库存。
3. **对账死路径**：`PayOrderTask` 依赖 `isPayTradeInitiated` 的 Redis 标记过滤待对账单，
   但 `markPayTradeInitiated` 全库无生产调用方——轮询永远空转，MQ 支付事件丢失时无兜底。
4. **quote 锁失效**：V2 `createConfirmed` 的 `FOR UPDATE` 无外层事务即释放；真正的互斥
   `consume` CAS 发生在建单全部副作用之后——并发重复请求先落单后被 409，重演孤儿单。
5. **幂等账本事务声明失效**：`insertProcessing` 注释称"独立事务"，实际 TransactionTemplate
   默认 REQUIRED 传播加入调用方事务——秒杀入口 `@Transactional` 回滚时"请求已受理/已失败"
   留痕一并消失。
6. **Mock 渠道关单不容忍缺失意图**：`closeOrder` 对不存在的支付意图抛错，孤儿单消费关单
   消息会无限重投（与缺陷 1 联动）。

## 决定

1. **超时关单消息写入 Phase 3 短事务内**（Outbox 与订单同事务落库）：
   `TransactionalMqSender.sendAfterCommit` 在活跃事务内的语义（savePending 参与外层事务 +
   afterCommit 异步投递）恰好支撑这一点——订单与收敛消息同生共死。Phase 4 失败的遗留单
   由 15 分钟延时消息关闭，且库存侧（决定 2）不会虚增。
2. **库存恢复前置校验 + 账本只增不删**：`restoreOrderStock` 要求
   `stock_change_record` 中存在 `order-deduct:{payOrderId}` 记录才回补；移除
   `releaseOrderDeductKey`（关单恢复前删除扣减键）——deduct 记录从此保留，同时承担
   "是否扣减过"的判断依据与完整审计链；重复恢复仍由 `order-close:*` 幂等键独立挡住。
   历史数据无迁移问题：删键只发生在恢复时序内部，存量未恢复单的 deduct 键仍在。
3. **支付轮询对账改为按态轮询**：`PayOrderTask` 按 `order_status=0 AND order_time <
   now-180s` 分页拉取直接查渠道（PENDING/意图缺失返回 null 跳过、单笔失败不断批），
   删除永不置位的 Redis 标记闸。阈值/批量可配（`smartlect.pay.poll-min-age-seconds/ poll-batch-size`）。
4. **quote claim-first**：新增 `OrderQuoteService.claim`——在短事务内完成行锁 + 校验 +
   一次性占用（consume 提前到任何建单副作用之前）；`createOrder` 失败时 `release`
   逆向释放（仅当占用者仍是本请求）。并发重复请求在 claim 处即被 409，不再先落单后冲突。
5. **幂等账本 REQUIRES_NEW**：`insertProcessing` 与 `markFailed` 走 REQUIRES_NEW 独立提交
   （"受理/失败"留痕跨调用方回滚存活，同键重放得到确定性结果）；`markCompleted` 保持参与
   调用方事务（无外层事务时自动提交）——只有业务真正提交后响应才可重放，避免
   "台账已 COMPLETED 而业务回滚"的假成功。
6. **Mock 渠道对账幂等**：`closeOrder` 对意图不存在视为已关闭（对齐 `markClosed` 0 行静默）；
   `queryOrder` 对意图不存在返回 null（渠道侧无结果语义）。`paySuccess` 的 `requireIntent`
   仍严格。
7. **查询索引补齐**：order_info（user,order_time / status,order_time / pay_order_id）、
   order_item（order_id）、order_coupon_rel（user_coupon_id）、物流 record（order_id）、
   pay_trade_record（status,create_time / user,create_time）、user_coupon（user,status / status）、
   product_info（category / pcategory / status），全部 `ALGORITHM=INPLACE, LOCK=NONE` 在线 DDL。

## 后果

- 三处高危缺口（孤儿单、库存虚增、对账死路径）闭环；两处声明与实现不符（注释、锁语义）对齐。
- 行为变更一处：秒杀入口 `@Transactional` 下命令失败后，同键重放从"凭空重新执行"变为
  409 回放"原请求执行失败"（与 V2 路径既有契约一致，更安全）；批次二将移除该入口的
  外层事务，进一步消解双事务模型矛盾。
- 附带修复三处陈旧 IT（CI 只跑 surefire 从未执行过）：MiddlewareIT 仍断言 25ef508
  已删除的 R__ 快照文件、OrderMoneyPersistenceIT 漏注入 RefundSagaTransactionService
  后加的 orderStateMachine、CoPurchasePersistenceIT 按旧口径（退款计入）断言流行度。
- 非目标：时间列全量迁移 epoch（新表沿用 V4 epoch 惯例）、按数量部分退款、真实支付通道。

## 验证

- 新增 `OrderConsistencyFixIT`（真 MySQL + Spring 事务同步）：4 线程并发 claim 恰一赢家、
  失败释放后可重占、外层回滚后 FAILED 台账独立存活且同键 409 回放失败消息。
- `OrderCreationIntegrityTest` 增"关单消息必须写入 Phase 3 事务回调内"的时序断言；
  `SkuStockServiceTest` 增"无 deduct 记录跳过恢复/有记录照常恢复且不再删键"；
  `PayOrderTaskTest` 4 例锁定轮询集合与容错；`PayChannel4MockIT` 增缺意图两例。
- 全量 `mvn test`（10 模块 502 用例）与 `mvn -Pintegration verify`（6 个 IT 类含 8 库
  fresh-migrate 回归）全绿，证据见 eval/verification/2026-10-14/batch1-p0-consistency/。
