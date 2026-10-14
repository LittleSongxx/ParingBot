# ADR-0020：退款全额返还优惠券

- 日期：2026-10-14；状态：已接受（批次三实施）；关联：ADR-0018/0019
- 用户决策（2026-10-14 评审计划确认）：全额退款返还优惠券（行业主流），部分退款不还。

## 决定

- 触发：退款 Saga 收尾 `finalizeOrderRefund` 判定整单全额退（无剩余正常明细）时，在同一
  事务内查用券关系（本单优先、聚合兄弟单回退）并经 Outbox 发 `refund-coupon-return` 事件
  （幂等键 `refund-return-coupon:{payOrderId}`）。
- 消费：coupon 模块 `RefundCouponReturnListener`（容器幂等租约 + TTL 7 天）→
  `returnCouponForRefund`：USED→NOUSE 条件更新；已 NOUSE 幂等成功；券模板过期或状态非
  USED（如秒杀占位 CANT）按终态跳过；并发竞争后重读确认。
- 旧状（退款不还券且无说明）确认为缺陷修复 + 产品行为变更。

## 后果

- 消费失败走既有 MQ 三级重试与补偿重放兜底；事件与退款收尾同事务，不会出现"退了款没发还券消息"。
- 多订单聚合的口径：券关系挂聚合首单，任一含券订单全额退即还（单店演示口径，记录于此）。

## 验证

`RefundCouponReturnHookTest`（全额退发事件/部分退不发）+ `RefundCouponReturnServiceTest`
（还券/幂等重放/过期跳过/CANT 跳过/缺失跳过 五分支）；全量 mvn test 绿。
