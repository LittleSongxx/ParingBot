# ADR-0019：订单域结构重构——上帝类拆分、paySuccess/cancel 短事务化、秒杀流程统一

- 日期：2026-10-14
- 状态：已接受（批次二实施）
- 关联：ADR-0018（一致性修复）、ADR-0006（移除 Seata 后的事务纪律）

## 背景

评审确认三类问题：① `OrderInfoServiceImpl` 1509 行上帝类（CRUD/下单/回调/取消/统计混装）；
② `paySuccess`/`cancelOrder`/秒杀两入口仍是 RPC-in-`@Transactional`——与代码注释自己记录的
2026-10-05 压测事故（连接池抽干）同型，普通下单路径已修而这三处未修；③ 秒杀与普通下单
两套并行实现且事务模型相反，漂移风险高（秒杀的 RUSH_TIMEOUT 消息发送依赖外层事务才与
订单原子，一旦有人去掉 `@Transactional` 就会重演孤儿窗口）。

## 决定

1. **拆分为「门面 + 三个领域服务」**：`OrderCreationService`（报价/下单/V2 确认，三阶段
   编排）、`OrderPaymentService`（支付回调/冲突/迟到退款/实付分摊）、`OrderCancellationService`
   （取消/超时关单/解券/回补）；`OrderInfoServiceImpl` 保留为门面（查询/富化/统计/确认收货 +
   契约委托），共享状态判定收敛到 `OrderFacts`。新类全部构造器注入；顺带删除两个无引用死字段
   （appConfig/reliableMessageSender）。计划中的第 4 个查询服务并入门面保留（拆分后门面约
   500 行、无事务语义，独立成类收益低于迁移风险——显式偏离记录于此）。
2. **paySuccess 短事务化**：assertSettled 等远程读在事务外 → 物流补齐/状态机 CAS/
   LOGISTICS_STEP Outbox/实付分摊收进 TransactionTemplate 短事务 → 券核销与 markSuccess
   在事务外幂等执行（失败由支付事件重投驱动重试，重入由状态机 CAS 保证）。秒杀支付分支
   同构：CAS 循环与券关系读取在事务内，券激活/markSuccess 在事务外。
3. **cancelOrder 短事务化**：每条路径（用户取消/超时关单/秒杀取消）均为「读校验（无事务）→
   短事务 CAS 关单 → 事务外幂等远程收敛（markClosed/渠道关单/解券/回补库存，失败走补偿
   台账或重投收敛）」。生命周期锁继续覆盖整段序列。
4. **秒杀统一到同一事务纪律**：`prepareCouponRush` 改为 Phase1 只读校验（远程）→ Phase2
   Redis 预占+远程扣减（事务外）→ Phase3 短本地事务建单（order+rel+item+RUSH_TIMEOUT
   Outbox 原子落库，零远程调用）→ Phase4 事务外创建占位券（失败同步补偿释放预占，订单由
   超时关单收敛）。`postCouponRushOrder` 的唯一本地写是单条条件 UPDATE（自原子）。
   两套流程从此共享同一套三阶段骨架与失败收敛语义。

## 后果

- 行为保持：门面接口与既有 20+ 测试类语义不变（多数测试零改动通过；4 个直连实现的测试
  改为直连领域服务）。
- 行为微调：支付回调中实付分摊先于券核销/markSuccess 执行（原为最后一步）——分摊与状态机
  翻单同事务提交，失败整体回滚，一致性更强。
- 连带修复一个潜在缺陷：去掉秒杀 `@Transactional` 后，RUSH_TIMEOUT 消息若不显式收进
  TransactionTemplate 将与订单落库失去原子性（新结构从源头杜绝）。

## 验证

- 新增结构性锚定测试：`CouponRushOrderCreationTest`（关单消息在建单事务回调内 + 占位券在
  事务外 + 占位券失败补偿释放预占）、`OrderPaymentServiceTest`（assertSettled → 短事务 →
  markSuccess 顺序）。
- 全量 `mvn test`（10 模块）与 `mvn -Pintegration verify` 全绿，证据见
  eval/verification/2026-10-14/batch2-structure-refactor/。
