# 三批次改造后全面自查修复

日期：2026-10-14。对 2026-10-13 三批次（IK/RocketMQ/Dubbo）改造的系统性自查，
发现并修复 8 处问题；全部为独立修复，不改变三批次已验证的行为。

## 发现与修复

| # | 问题 | 严重性 | 修复 |
| --- | --- | --- | --- |
| 1 | **build-rocketmq.sh 的 `\$` 转义 bug**：Topic 预建循环变成遍历字面字符串且变量不展开（`\$NODE1_IP` 按字面量传给 ssh），集群 Topic 永远建不成；且该段位置在 broker 拉起之前（时序也不对） | 真 bug | 重写为正确引号并移到三节点拉起之后，`bash -n` 语法验证 |
| 2 | 9 个 yml 残留 `spring.cloud.openfeign.sentinel.enabled` 配置块（依赖已删，脏配置） | 清理 | 删除 |
| 3 | DubboInternalAuthFilter provider 侧写 MDC traceId 后不清理——Dubbo 线程池复用线程会把上一请求的 traceId 串入下一请求日志 | 真 bug | 拆 authorizeAndInvoke + finally 清理 |
| 4 | UserDubboServiceImpl 残留未用 import；StockDubboServiceImpl 全文 FQN 杂乱 | 清理 | 整理 import |
| 5 | docs/runtime.md 端口表仍写 RabbitMQ 15672 | 文档 | 更新为 RocketMQ gRPC 8081 与三容器描述 |
| 6 | smartlect-common 的 es-settings.json 孤儿文件（早期 spring-data-elasticsearch 方案残留，零引用） | 清理 | 删除 |
| 7 | RocketMqConsumerContainer 的 dispatch 模板（COMPLETED 跳过/BUSY 延后/异常重试链/坏消息归档）无单测（批次二遗留测试债） | 测试债 | 新增 RocketMqConsumerContainerTest 7 用例全绿 |
| 8 | 补偿重放不携带定时语义的潜在坑（当前无 HIGH+delay 组合，安全） | 已知边界 | 写入 ADR-0016「已知边界」 |

## 核查过但确认无问题的项

- Outbox 的 dispatchPendingBatch 走 tryDispatch（带剩余延迟折算），定时消息经定时扫描补发不丢延迟。
- stock/coupon/admin 库无 local_message_outbox 表，但这些服务也无 transactionalMqSender 调用（grep 证实），无越界写表。
- MqConsumeReplayRouter 对新旧两种 routing_key 形态（topic:tag 与旧队列名）的分支边界正确。
- Flyway 迁移编号（V2/V3/V4 各库）无冲突、无对已应用迁移的修改。
- 全部主代码与测试对 amqp/openfeign/FeignClient 的引用为零残留。

## 验证

- mvn compile 零错误；smartlect-common 全量测试（含新增 7 用例）与 backend 全量单测通过。
- `bash -n` 集群脚本语法通过。

## 关联

自查对象：b3cca6b / ec9e6fa / ec794c6 / b3c5787 四个提交。
