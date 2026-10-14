# ADR-0021：观测链路贯穿与日志脱敏（批次四）+ Sentinel 动态规则（批次六追加）

- 日期：2026-10-14；状态：已接受（批次四部分实施，批次六部分见文末追加）；关联 ADR-0018/0019

## 背景

评审确认：网关不生成/传播 traceId（入口断裂）、MQ 消费线程与异步线程池无 MDC（异步边界断裂）、
全仓无 logback 配置与脱敏（PII 直落日志）、pageSize 无上限、参数校验失败吞成通用文案无字段提示。

## 决定（批次四）

1. **网关 TraceIdGlobalFilter（order=-300）**：入口统一裁决 traceId——合法 W3C traceparent 的
   trace-id 段优先，其次合法 32 位十六进制 X-Trace-Id，否则生成；剥客户端伪造头后下发
   X-Trace-Id，响应回显；traceparent 原样透传不伪造。网关不依赖 common，W3C 解析内联最小实现。
2. **MDC 贯穿**：MQ 发送随消息携带 traceId user property（RocketMqClientHolder），消费分发
   恢复/清理 MDC（RocketMqConsumerContainer）；两个自定义线程池（mq-async、coupon-cache-rebuild）
   加 MdcTaskDecorator。
3. **日志脱敏**：MaskingMessageConverter（手机号前 3 后 4、身份证前 6 后 4、邮箱本地部分打码）
   + common resources 根 logback-spring.xml（9 服务自动拾取，%maskingMsg + traceId 输出，
   仅控制台——进程编排负责落文件）；网关独立最小配置（无 PII，不带 converter）。
4. **分页上限**：PageUtils 单页上限 100（系统属性 smartlect.page.max-size 可调）。
5. **字段级校验错误**：BindException/MethodArgumentNotValidException 在 CODE_600 之外随 data
   返回 [{field, message}]，前端可提示具体字段。
6. **线程池参数修正**：mqAsyncExecutor 队列 2000→200 使 max 生效、参数可配、停机 drain 30s。

## 验证

TraceIdGlobalFilterTest（4 例：W3C 提取/伪造头覆写/无上下文生成/畸形回退）、
MaskingMessageConverterTest（2 例）、MdcTaskDecoratorTest（2 例）、PageUtilsCapTest（1 例）；
全量 mvn test 绿。

## 批次六追加（Sentinel 动态规则 / CORS / 白名单单源 / Outbox 时钟）

见 docs/改动记录/2026-10-14/批次六-可靠性与清理.md（本 ADR 随批次六提交时补齐该节）。
