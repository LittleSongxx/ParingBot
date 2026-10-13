# Smartlect 本地运行

更新：2026-10-07（新增 Canal / xxl-job-admin 容器，Nacos 兼作配置中心）。从项目根目录执行 `./scripts/dev.sh bootstrap`，探测空闲端口并生成本项目随机凭证，保存在 Git 忽略的 `run/runtime.env`（权限 600）。

## 基础设施（9 个容器）

| 服务 | 默认端口 | 说明 |
|---|---|---|
| MySQL 8.4 | 13306 | 8 个业务库 + nacos/growth/xxljob（无 Seata） |
| Redis 7.4 | 16379 | Sa-Token 会话 + Redisson 锁/限流 |
| RocketMQ 5.3 | gRPC 8081（namesrv 9876） | Outbox 可靠消息 + 任意精度定时消息（namesrv/broker/proxy 三容器） |
| Nacos v2.5 | 18848 | 服务发现 + 配置中心（`SMARTLECT_GROUP` 下 `smartlect-common.yml` 与 `smartlect-{服务}.yml`） |
| Elasticsearch 8.19 | 9200 | IK 中文分词（自建镜像预装，compose 已指向 build） |
| Qdrant 1.15 | 6333 | 1024 维 HNSW 向量检索 |
| Canal 1.1.8 | 11111 | 伪装 MySQL 从库解析 binlog 直投 RocketMQ，驱动商品索引增量同步与缓存失效 |
| xxl-job-admin 2.5 | 18090 | 调度中心（九个定时任务由 `@Scheduled` 迁移而来，表结构见 `deploy/sql/16-xxljob.sql`） |
| LiteLLM | 14000 | 模型路由网关，挂在 `litellm` profile 下，默认不随 `infra-up` 启动 |

> LangGraph checkpointer 已移除（2026-10-05，ADR-0009 后记）：图状态无消费者（跨 run 不复用、崩溃不恢复、不用 interrupt），会话事实源是 MySQL。PostgreSQL 容器与 psycopg 依赖随之退役。

> 配置中心：各服务的 `spring.config.import` 从 Nacos 拉取 `smartlect-common.yml` 与
> `smartlect-{服务}.yml`，全部写成 `optional:`——配置中心缺这条 dataId 或不可达时静默退回
> 本地 `application.yml`，不阻断启动。改完本地配置用 `python3 scripts/nacos_config_push.py`
> 重新推送（脚本会剥掉"从 Nacos 导入自身"的行，避免配置中心自引用）。
>
> **`refreshEnabled=false`：配置只在启动时拉取，改完 Nacos 里的配置需要重启应用才生效。**
> 起因是一次线上故障：Nacos 客户端 3.0.3（Spring Cloud Alibaba 2025 引入）与 2.5.x 服务端
> 组合下配置长轮询不挂起，退化成每 200ms 一次的短轮询，九个服务合计每天产出约 4GB 日志，
> 写满磁盘后 MySQL 退出。仓库内没有任何 `@RefreshScope` Bean，热刷新本就没有消费者，
> 关掉监听没有功能损失。详见 `docs/改动记录/2026-10-07/线上故障-配置请求风暴.md`。

```bash
./scripts/dev.sh infra-up   # 启动上述全部容器并等待健康
./scripts/dev.sh infra-check
```

## 应用进程（12 个）

| 进程 | 端口 | 说明 |
|---|---|---|
| assistant | 18000 | FastAPI（Python，无 worker 进程） |
| user | 18105 | 账户/地址/RBAC/Sa-Token 登录 |
| product | 18106 | 商品/SKU/分类 |
| stock | 18108 | 库存（条件更新） |
| order | 18104 | 订单/退款 Saga/Outbox |
| pay | 18103 | mock 支付（intent 权威） |
| cart | 18102 | 购物车 |
| coupon | 18107 | 优惠券/秒杀 Lua |
| admin | 18101 | 管理端 BFF |
| gateway | 18080 | SCG 网关（Sa-Token 校验） |
| web-user | 18180 | Vue 3 用户端 |
| web-admin | 18181 | Vue 3 管理端 |

```bash
./scripts/dev.sh build   # 编译 Java + assistant venv + 前端
./scripts/dev.sh up      # 按顺序启动 12 进程（Java 先声明队列 → assistant → 前端）
./scripts/dev.sh check   # 三栈全量测试
./scripts/dev.sh status
./scripts/dev.sh down
```

## sa-token 配置

`smartlect-common.yml` 全局共享 `sa-token.token-name: token`——所有业务服务自动继承，各服务不得覆写 token-name（Redis 键前缀会不一致导致互读不到会话）。管理端 StpAdminLogic 的 `tokenName: adminToken` 在 `StpAdminLogic.java` 注册。

## 常用操作

```bash
./scripts/dev.sh seed-store     # 示例货架 + 知识灌入
./scripts/dev.sh reset-demo     # 重置演示数据
./scripts/dev.sh model-mode     # 切换 mock/live
./scripts/dev.sh catalog        # 安装商品目录
```
