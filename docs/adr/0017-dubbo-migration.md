# ADR-0017: 服务间 RPC OpenFeign → Dubbo 3

日期：2026-10-13
状态：代码已合入（本机 WSL2 联调未通，见「后果」）

## 背景

对齐国内大厂主流 RPC 选型（Dubbo triple/dubbo 协议 + Nacos）。约束：assistant（Python）
与运维工具直调 HTTP /internal + X-Internal-Token，该通道必须保留。

## 决定

- Dubbo 3.3.6 + Nacos 注册（复用 SMARTLECT_GROUP；强制 nacos-client 2.5.1——Dubbo 传递
  的 3.0.3 与 Nacos Server 2.5 gRPC 不兼容）。
- 双通道：Dubbo provider 直接委托 internal controller（@Valid/ResponseVO/业务逻辑零重复）；
  HTTP /internal 原样保留。
- 契约：7 个 Dubbo 接口 59 方法（原 FeignClient 签名平移，头参数转显式参数）；
  XxxFeignSupport 门面签名不变、内部换 @DubboReference（十余个 mock 门面的单测零改动）。
- 鉴权：SPI Filter 双端传验 X-Internal-Token（invocation attachment；常量时间比较），
  X-Trace-Id 链路一并透传；委托用户经 DelegatedUserIdentity 新增 ThreadLocal 通道。
- 降级：fallbackFactory 语义由 RpcException→BusinessException 翻译承接（FeignResponseSupport
  保留类名）；Sentinel 16 条熔断规则换 Dubbo 资源名。

## 后果

- 已验证：全量单测绿、provider 注册成功、双端鉴权通过。
- **未解决**：WSL2 双栈宿主上 Dubbo Netty 调用网络层失败（HTTP 与 gRPC 均正常），已加
  preferIPv4Stack 部分改善；最终排查方向与「服务器 Linux 复测大概率不复现」的判断记录于
  `docs/改动记录/2026-10-13/OpenFeign迁移Dubbo3.md`，联调通过前不部署线上。
- Dubbo registry 关闭 config/metadata-center 复用（其 nacos 客户端以 group 为 tenant
  导致 403），配置中心职责仍由 Spring Cloud Nacos 承担。
