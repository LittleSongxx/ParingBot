# ADR-0008：会话、权限与内部调用分三层校验

- 状态：Accepted
- 日期：2026-10-17
- 范围：gateway / common / user / admin
- 相关代码：`backend/smartlect-gateway/src/main/java/com/smartlect/cloud/gateway/filter/AuthGlobalFilter.java`、`backend/smartlect-common/src/main/java/com/smartlect/config/SaTokenInterceptorConfig.java`、`backend/smartlect-common/src/main/java/com/smartlect/security/StpAdminLogic.java`、`backend/smartlect-common/src/main/java/com/smartlect/web/InternalApiAuthFilter.java`

## 背景

浏览器到 Java 服务之间有三类判断：这个 token 有没有会话、这个用户有没有权限、这条数据是不是他的。把它们都塞进网关会导致网关依赖业务、无法表达数据归属；只靠前端隐藏按钮则没有安全性。

## 决策

1. **双 realm**：用户端 `StpUtil`（tokenName=`token`，允许并发登录）；管理端 `StpAdminLogic`（tokenName=`adminToken`，不允许并发登录）。两套 token、两套会话键、两套权限。
2. **网关只做会话键检查**：用户端读 `token:login:token:{token}` 的 `loginId`；管理端 `hasKey adminToken:admin:token:{token}`；不注入身份头，先剥掉客户端伪造的 `X-User-Id`/`X-Internal-Token`/`X-Admin-*`。
3. **服务端做细粒度鉴权**：`SaTokenInterceptorConfig` 校验登录，`@SaCheckPermission(type="admin")` 校验权限点，业务层校验订单/地址归属；权限来自会话，不来自前端。
4. **内部调用 fail-closed**：`InternalApiAuthFilter` 对 `/internal/**` 做 `X-Internal-Token` 常量时间比较，未配置令牌一律拒绝；Dubbo 用同一个令牌。
5. **白名单精确化**：公开读接口逐条列出，不用整前缀通配；新增写接口必须走受保护前缀。
6. **展厅身份服务端拒绝**：visitor/gallery 的只读限制在过滤器、拦截器、服务层三层兜底；前端隐藏只是体验。

## 备选方案

- **网关统一签发 JWT/身份头**：下游信任头，容易伪造/漂移；项目选择下游从会话取身份。
- **网关做 RBAC**：网关不知道数据归属，且每个新接口都要改网关；不采用。
- **共享内部令牌改成 per-service 签名**：更安全，但需要重做全部内部调用约定；当前作为已知风险，见 README。
- **只用前端权限**：无服务端拒绝点，不可接受。

## 后果

**正向**

- 网关轻、服务端权限可表达数据归属；双 realm 互不影响。
- 伪造身份头被剥离；内部接口未配置令牌即拒绝。
- 展厅账号的只读限制可审计。

**代价**

- 每个服务都要正确配置 Sa-Token/内部令牌；新增公开接口必须同步白名单。
- 内部令牌是共享令牌，泄露影响面大（已知接受风险）。
- 试用身份是项目自定义策略，不是通用 RBAC 模型。

## 何时重审

- 内部调用需要最小权限/审计 actor；
- 引入 SSO/OAuth/多租户；
- 公开接口数量增长，白名单维护成本过高。

## 证据

- 网关：`AuthGlobalFilter`、`InternalTokenGlobalFilter`。
- 服务端：`SaTokenInterceptorConfig`、`StpAdminLogic`、`SmartlectStpInterface`。
- 试用身份：`TrialAdminAccess`、`TrialUserWriteFilter`、`TrialIdentities`。
- 测试：`AuthGlobalFilterTest`、`TrialOrderPrivacyTest`、`AdminControllerSurfaceTest`。
