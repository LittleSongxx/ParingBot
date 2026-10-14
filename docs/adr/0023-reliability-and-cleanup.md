# ADR-0023：可靠性细节与清理——Outbox DB 时钟、Sentinel Nacos 数据源、CORS、死代码

- 日期：2026-10-14；状态：已接受（批次六实施）；关联 ADR-0016/0021

## 决定

1. **Outbox 时钟 DB 化**：claimForDispatch/markFailed 的租约与退避时间全部由数据库 NOW()
   推导（SQL `DATE_ADD(NOW(), INTERVAL …)`），消除跨实例应用时钟漂移超过租约期（默认 30s）
   导致的双重投递窗口；兜底扫描批量默认 30→10、锁 TTL 可配（`mq.outbox.dispatch-lock-ttl-seconds`）。
2. **Sentinel 动态规则**：引入 sentinel-datasource-nacos，网关流控与 Dubbo 熔断规则支持
   Nacos 热更（`smartlect.sentinel.{gateway,dubbo}-rules-data-id` 配置后启用，代码注册规则
   降级为兜底；示例 JSON 见 deploy/sentinel/）；**修复配置键失效 bug**（yml feign-rules-enabled
   ↔ Java dubbo-rules-enabled 永不生效）。
3. **CORS**：网关 CorsWebFilter，默认关闭，`smartlect.cors.allowed-origin-patterns` 启用
   （此前全仓无 CORS，隐性依赖 nginx 同源）。
4. **死代码/卫生**：删 Seata 残留 file.conf；OrderStatusEnum Optional 误用修复（未知状态
   返回 null 而非 NoSuchElementException）；DateUtil 换 ConcurrentHashMap 且 parse 失败
   抛异常（旧"回退当前时间"是危险语义，调用方均为 format→parse 闭环）；STATUC_* 拼写修正
   （STATUS_* + @Deprecated 兼容旧名）；券分摊前按 orderId 排序（确定化）；
   mqAsyncExecutor 队列 2000→200（批次四已含）。
5. **保留决策**：MQ 补偿 payload 落库保持原文（重放保真），访问面由批次五权限点控制；
   白名单双处维护收敛为"同键同默认值 + 互链注释"（完全单源需改网关与服务端两侧读取，收益
   低于风险，列为后续演进）；Sa-Token 裸键读 4 处收敛同 ADR-0022 立场。

## 验证

Outbox 单测与 MiddlewareIT 真库回归全绿（租约 SQL 改 DB 时钟后 8 库迁移与投递用例通过）；
MqSchedulingLockScopeTest 适配可配参数。全量 mvn test 与 -Pintegration verify 绿，
证据见 eval/verification/2026-10-14/batch6-reliability/。

## 启用/回滚

新配置项：`mq.outbox.dispatch-lock-ttl-seconds`（默认 4）、`mq.outbox.dispatch-batch-size`
（默认 10，原 30）、`smartlect.sentinel.{gateway,dubbo}-rules-data-id`（默认空=代码兜底）、
`smartlect.cors.allowed-origin-patterns`（默认空=关闭）。回滚：回退本提交即可（无数据迁移）；
Nacos 规则回滚 = 删 data-id 配置并重启。
