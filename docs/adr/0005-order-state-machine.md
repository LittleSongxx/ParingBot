# ADR-0005：订单状态机用 CAS，支付生命周期另加锁

- 状态：Accepted
- 日期：2026-10-17
- 范围：order
- 相关代码：`backend/smartlect-order/app/src/main/java/com/smartlect/state/OrderStateMachine.java`、`backend/smartlect-order/api/src/main/java/com/smartlect/api/enums/OrderStatusEnum.java`、`backend/smartlect-order/app/src/main/java/com/smartlect/state/OrderStateEvent.java`、`backend/smartlect-common/src/main/java/com/smartlect/component/PayOrderRedisComponent.java`

## 背景

订单状态是交易的核心事实，支付回调、用户取消、超时关单、发货、退款可能并发到达。直接 `UPDATE order_info SET order_status=?` 会让后到的请求覆盖先到的状态，出现“待支付直接变已发货”“已取消又被发货”等幽灵跳变。

## 决策

1. **状态 + 事件表**：`OrderStateMachine` 只允许预定义迁移；非法迁移在解析目标状态时抛错。
2. **CAS 条件更新**：更新时把“期望状态”放进 WHERE，影响行数为 0 由调用方解释（并发者已成功、非法流转、订单不存在）。
3. **幂等重入**：期望状态等于目标状态且无额外 patch 时，退化为读比对，避免无谓 UPDATE。
4. **支付生命周期锁**：支付成功、超时关单、迟到支付退款可能同时发生；订单服务用 `payOrderId` 维度的 Redisson 锁覆盖“读订单 → CAS → 事务外核销券/标记支付单”的整段，状态机负责行级正确，锁负责流程级互斥。
5. **状态变更历史**：`order_status_log` 在 CAS 成功后同事务记录 from/to/event/operator/trace；创建写 `null → WAIT_PAYMENT / CREATE`，幂等重入与 0 行更新不写。`transitionPayOrder` 的批量 UPDATE 若只影响部分子单，抛错回滚（含日志），避免把未流转的单写成已流转；管理端用只读接口按写入顺序查询。

## 备选方案

- **直接覆盖更新**：简单，但会丢状态、无法解释 0 行，不采用。
- **版本号乐观锁**：可以防 ABA，但订单状态本身就是条件；当前 CAS 已足够，版本号不是必需。
- **数据库行锁/悲观锁**：支付生命周期跨多个远程步骤，长时间持锁会拖垮连接池；用短锁 + CAS 更合适。
- **完整状态机框架（Cola/Spring StateMachine）**：当前 9 个状态、10 个事件，轻量自封装足够；引入框架会增加学习/维护成本。

## 后果

**正向**

- 非法迁移被拒绝，并发竞争表现为可解释的 0 行。
- 支付/关单/退款竞态由生命周期锁串行化，避免“已关闭订单被复活”。
- 状态历史可审计，便于对账和客服排查。

**代价**

- 调用方必须解释 0 行，不能简单当失败；增加了代码复杂度。
- CAS 只保护单行，跨多张子单的批量迁移需要额外处理。
- 状态历史会增加写入量，需要索引/归档。

## 何时重审

- 状态数量/事件数量增长到需要可视化编排；
- 需要跨服务状态订阅/事件溯源/CQRS；
- 批量迁移（按 payOrderId）出现部分成功语义问题。

## 证据

- 迁移表：`OrderStateMachine#buildTransitions`。
- CAS：`transition`、`transitionPayOrder`。
- 支付锁：`PayOrderRedisComponent#runWithPayOrderLifecycleLock`。
- 测试：`OrderStateMachineTest`、`OrderPaymentServiceTest`、`OrderAggregateCancellationTest`。
