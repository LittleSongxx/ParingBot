# ADR-0009：可观测性与安全基线先做“能定位”，不做全栈 APM

- 状态：Accepted
- 日期：2026-10-17
- 范围：gateway / common / 各服务
- 相关代码：`backend/smartlect-common/src/main/java/com/smartlect/web/TraceIdFilter.java`、`backend/smartlect-gateway/src/main/java/com/smartlect/cloud/gateway/filter/TraceIdGlobalFilter.java`、`backend/smartlect-common/src/main/java/com/smartlect/logging/MaskingMessageConverter.java`、`backend/smartlect-common/src/main/java/com/smartlect/metrics/SmartlectMetrics.java`、`backend/smartlect-common/src/main/java/com/smartlect/interceptor/SlowSqlInterceptor.java`

## 背景

项目是单店演示，不可能也不需要在本地搭完整 APM/SLO/混沌平台；但如果没有 traceId、指标、脱敏、慢 SQL，出现问题时只能猜。安全同理：不需要企业级零信任，但登录锁、内部令牌、生产校验、参数校验这些基线必须有。

## 决策

1. **TraceId 贯穿**：网关优先接受 W3C `traceparent`，否则合法 `X-Trace-Id`，再否则生成 32 位 hex；写入 MDC/响应头；Dubbo 透传、RocketMQ 写入消息属性、线程池用 `MdcTaskDecorator`。
2. **日志脱敏**：`MaskingMessageConverter` 对手机/身份证/邮箱打码，`%ex` 走同类脱敏；不把凭据、买家原文写进日志。
3. **指标**：`SmartlectMetrics` 统一 `smartlect_<域>_<事件>_total`，覆盖订单创建、幂等重放/冲突、库存不足、Outbox 投递/补偿、商品缓存等；标签限制基数。
4. **慢 SQL**：`SlowSqlInterceptor` 默认 200ms，只记录 mapperId、耗时、traceId、折叠后的 SQL 骨架，不记录参数；累计慢 SQL 指标。
5. **限流与保护**：网关 Sentinel 规则 + 注解限流；鉴权/登录接口单独配额；限流键按主体 + 方法，避免接口互相挤占。
6. **安全基线**：登录失败锁定、验证码、BCrypt、内部令牌 fail-closed、生产模式校验（令牌长度/默认密码/数据库账号/通配绑定）、管理端敏感操作二次确认。
7. **Mock 支付加固**：`/internal/pay/mock/complete` 在内部令牌之外校验 HMAC-SHA256（方法/路径/支付单/金额/时间戳/nonce），时间窗 300 秒，nonce 在 Redis SETNX 防重放；密钥由环境变量注入，生产拒绝开发默认值。渠道流水 `pay_mock_channel_ledger` 与支付意图/退款表分开，`payDailyReconcile` 只报告差异、不自动改账。
8. **不做**：本地不搭完整 APM、SLO、告警平台、混沌工程；这些在规模上来后再补。

## 备选方案

- **接入完整 APM（SkyWalking/OTel + Tempo + Prometheus + Grafana）**：能力强，但本地资源/运维成本高；当前用 traceId + Micrometer + 日志足够定位。
- **只在网关打日志**：无法跨服务追踪，不采用。
- **记录 SQL 参数**：排障方便但泄露隐私/凭据；只记录骨架。
- **企业级零信任/SSO**：超出单店范围；当前双 realm + 内部令牌是合理折中。

## 后果

**正向**

- 能用 traceId 串起网关/服务/Dubbo/MQ；慢 SQL、Outbox 积压、幂等冲突有指标。
- 日志不落敏感数据；生产启动有安全门禁。
- 成本低，不引入额外基础设施。

**代价**

- 没有全链路拓扑、SLO、自动告警和混沌演练；故障定位仍依赖人看日志/指标。
- 指标是应用内计数器，不是完整监控平台；需要外部采集才有长期趋势。
- 限流/安全是基线，不是企业级风控。

## 何时重审

- 服务数量/流量增长，手工定位不可维护；
- 需要 SLO/错误预算/自动告警；
- 需要跨团队审计/合规/零信任。

## 证据

- Trace：`TraceIdFilter`、`TraceIdGlobalFilter`、`MdcTaskDecorator`。
- Mock 支付：`MockPaymentSignatureVerifier`、`PayMockChannelLedgerService`、`PayDailyReconcileTask`；测试 `MockPaymentSignatureVerifierTest`、`PayChannel4MockIT`。
- 脱敏：`MaskingMessageConverter`、`MaskingThrowableProxyConverter`。
- 指标：`SmartlectMetrics`。
- 慢 SQL：`SlowSqlInterceptor`。
- 安全：`UserLoginLockService`、`ProductionSafetyValidator`、`AdminSensitiveConfirmAspect`。
