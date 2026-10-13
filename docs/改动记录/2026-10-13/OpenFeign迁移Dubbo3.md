# OpenFeign 迁移 Dubbo 3（代码完成，本机联调未通）

日期：2026-10-13/14。同日批次三（批次一见 [IK分词切换.md](IK分词切换.md)、批次二见
[RabbitMQ迁移RocketMQ.md](RabbitMQ迁移RocketMQ.md)）。

## 需求

服务间 RPC 由 OpenFeign(HTTP) 切换为 Dubbo 3.3.6（Nacos 注册），对齐国内大厂主流；
HTTP /internal 端点保留给 assistant（Python）与运维工具，双通道共用同一 Service 层。

## 具体变更（已完成，全量单测绿）

- 依赖：7 个 api 模块 + 8 个 app 模块 + common 的 `spring-cloud-starter-openfeign`
  → `org.apache.dubbo:dubbo-spring-boot-starter:3.3.6`；common 另接
  `sentinel-apache-dubbo-adapter`；父 pom 排除 Dubbo 传递的 nacos-client 3.0.3
  （与 Nacos Server 2.5 gRPC 握手不兼容），强制对齐 2.5.1。
- 契约层：7 个 `@FeignClient` 与 7 个 `fallbackFactory` 删除，新增
  `com.smartlect.api.dubbo.{User,Stock,Coupon,Order,Pay,Product,Cart}DubboService`
  （59 个方法签名一致；`X-Smartlect-User-Id`/`Idempotency-Key` 头参数转显式参数；
  原契约中的死方法 `onConfirmed` 一并移除）。
- provider：各服务 `com.smartlect.dubbo.*Impl`（@DubboService 直接委托 internal
  controller，@Valid/ResponseVO 包装/业务逻辑零重复）；委托用户语义经
  `DelegatedUserIdentity` 新增的 ThreadLocal 通道传递（Dubbo 线程无 HTTP 上下文），
  controller 内 require()/requireAndMatch() 原逻辑复用。
- 消费门面：7 个 `XxxFeignSupport` 内部 `@Resource FeignClient` → `@DubboReference`
  （门面签名不变，10+ 个 mock Support 的单测零改动）；user 服务
  ImageModerationServiceImpl 的唯一 Support 外直连一并切换；
  `FeignResponseSupport.toBusiness` 的 FeignException/RetryableException 分支 →
  RpcException（超时/网络/禁止三分支映射原降级文案）。
- 鉴权：`DubboInternalAuthFilter`（SPI，@Activate consumer+provider）——consumer 往
  invocation attachment 写 X-Internal-Token 与 X-Trace-Id（替代
  FeignInternalAuthInterceptor/FeignTraceInterceptor，两者删除），provider 常量时间
  比较校验（未配置一律拒绝）；令牌经 `DubboCommonConfiguration` 从 Spring 环境桥接到
  Filter 静态 holder。SmartlectFeignConfiguration/SmartlectFeignErrorDecoder 删除。
- Sentinel：`FeignSentinelRulesConfig` → `DubboSentinelRulesConfig`，16 条熔断规则
  资源名从 `XxxFeignClient#method(params)` 改为 `接口全名.方法名`。
- 序列化：15 个未实现 Serializable 的契约 DTO/VO 补齐（含 serialVersionUID）。
- 配置：8 个 application.yml 增加 dubbo 段（registry=nacos+凭据、interface 注册模式、
  timeout 10s、retries 0、check false、`use-as-config-center/-metadata-center=false`
  ——Dubbo 复用 registry 为配置中心时其 nacos 客户端以 group 为 tenant 导致 403，
  项目配置中心已由 Spring Cloud Nacos 承担）；8 个启动类
  `@EnableFeignClients` → `@EnableDubbo(scanBasePackages="com.smartlect")`；
  runtime.py Java 进程追加 `-Djava.net.preferIPv4Stack=true`（见未完成项）。

## 验证

- backend 全量单测通过（BUILD SUCCESS）；全栈可启动：12 进程健康、9 Nacos 注册、
  启动冒烟通过；Dubbo provider 全部注册成功（INSTANCE/INTERFACE_REGISTER 日志，
  OrderDubboService/StockDubboService 等 7 个接口）。
- 消费侧鉴权链路已通（诊断输出 provider/consumer token 长度对齐 48=48，不再被拒）。

## 未完成项（如实记录，本机联调未通过）

下单链路经 Dubbo 调用时仍报「下游服务暂不可用」：provider 注册地址在双栈宿主上
出现 IPv6（已加 preferIPv4Stack 强制 v4，部分改善），此后仍有个别调用在网络层失败。
**当前判断**：WSL2 双栈网络与 Dubbo 3.3.6 Netty 的组合问题（Spring Cloud HTTP 调用
与 RocketMQ gRPC 在同机均正常）。下一步排查方向（未执行）：
1. 服务器 Linux 环境复测（大概率不复现，线上部署本就面向 Linux）；
2. 显式指定 `dubbo.protocol.host=127.0.0.1` 与 `dubbo.consumer.url` 直连验证；
3. 若确认 WSL2 特有，回归 Feign 或以 Dubbo 直连模式（url=）过渡。

在联调通过前，本批次**不部署线上**；批次一/二的线上化不受影响（二者已独立验证）。

## 启用与回滚

- 回滚：git revert 本批 → openfeign 契约与配置从 git 历史恢复 → build+up
  （FeignSupport 门面签名全程未变，回滚成本低）。

## 关联代码版本

分支 main，本文件同日 commit（批次三）。
