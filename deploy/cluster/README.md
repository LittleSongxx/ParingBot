# Smartlect 三节点集群编排

把中间件从 node1 单机提升为跨三台 ECS 的集群。应用副本的部署与同步流程见仓库根
README 的「部署覆盖面（三节点集群）」与 `deploy/cluster/scripts/sync-app-node.sh`
（历史设计稿 `docs/prod-hardening/` 已随文档面清理下线，Git 历史可查；其原始证据在
`eval/verification/cluster-hardening-20261006/`）。

## 拓扑

```
node1 (8c16g, 172.21.131.151)  MySQL 主 · Redis 主 · sentinel · rocketmq(broker+namesrv+proxy) · nacos-c1 · nginx · 监控
node2 (2c8g , 172.19.34.202)   Redis 副本 · sentinel · rocketmq · nacos-c2
node3 (2c8g , 172.19.34.203)   Redis 副本 · sentinel · rocketmq · nacos-c3
```

IP/端口集中定义在 [nodes.env](nodes.env)，脚本都从这里取，不再散落硬编码。

## 组件与取舍

| 组件 | 形态 | 关键设计 |
|---|---|---|
| RocketMQ | DLedger 三副本（Raft 自动选主） | 每节点 broker+namesrv+proxy（host 网络）；5.x 任意精度定时消息经 gRPC proxy；Topic/订阅组 autoCreate 重建，Outbox 补投未决消息，单机数据卷不动 |
| Redis | 1 主（node1）+ 2 副本 + 3 Sentinel | host 网络；`replica-announce-ip` 必填（否则 sentinel 记错地址）；主库补 `masterauth` 以支持降级后再认证 |
| Nacos | 3 节点 Raft | host 网络 8848/9848/7848；三成员**共用 node1 MySQL 的 `smartlect_nacos` 库**，所以从 standalone 切过来零数据迁移 |
| MySQL | 仍单机（node1） | 只增加内网绑定 172.21.131.151:13306 供 node2/3 访问；主从/切换不在本次范围 |

**为什么密钥不入库**：`gen-cluster-env.sh` 从 node1 既有的 `run/runtime.env` 读取
（Redis 密码、Nacos token/identity、MySQL 密码），只新增 erlang cookie 一项。
含密码的 `sentinel.conf` 也是构建期现场生成。仓库里没有任何凭据。

## 安全组（应用端口不对公网）

集群形态下应用绑 `0.0.0.0`——跨节点 Dubbo 与 nginx 上游需要它，这是有意为之，
所以**应用端口的安全边界是安全组，不是应用配置**：

- 公网只放行 **80/443**（nginx）与运维入口（22）。
- **18080-18108 只对节点内网放行**（18080 网关、18101-18108 各服务、18180/18181 前端）。
  任何一条放行到 `0.0.0.0/0` 的规则，都等于把 `/actuator/prometheus`（JVM/连接池/线程池指标）
  和绕过 nginx 的业务接口直接暴露给外网。
- 生产就绪模式（`SMARTLECT_PRODUCTION_READY=true` 或 prod profile）下，
  `ProductionSafetyValidator` 会拒绝"通配绑定 + actuator 暴露 prometheus"的组合。
  两个集群脚本已显式写入 `SMARTLECT_ALLOW_WILDCARD_BIND=true`，表示这条风险由安全组承担。
- 核对（从公网执行，应超时或被拒绝）：

  ```bash
  curl -m 3 http://<公网IP>:18081/actuator/health
  ```

## 执行顺序（全部在 node1）

```bash
cd /opt/cluster/scripts
bash distribute.sh                 # 生成 .env 并分发编排到 node2/3

# ↓ 以下步骤处于维护窗口内（应用会短暂不可用）
bash build-rocketmq.sh             # 生成 DLedger 配置 → 分发 → 三节点拉起 → 副本断言
bash build-redis.sh                # 2 副本 + 3 sentinel
bash build-nacos.sh                # 3 节点 Raft（会先停单机 nacos）
bash verify-cluster.sh             # 终态验证 + 证据落 /opt/cluster/evidence
```

前置：node1 的 `deploy/compose.yaml` 叠加 `deploy/cluster/compose.node1.yaml`
（mysql/redis 内网绑定；单机 rocketmq 三件套/nacos 挂 `single-only` profile）。

## 回退

```bash
bash revert-cluster.sh             # 停集群成员 → 撤 override → 起单机中间件 → 入口门禁
```

单机期的数据卷（`smartlect_rocketmq-store`/`smartlect_redis`/`smartlect_mysql`）全程未被改动，
集群成员用的是集群期新建的卷。回退不丢单机期数据。

## 与 2026-09 那套的关系

编排思路沿用 2026-09-15 的集群战役（那套只存在于服务器 `/opt/cluster`，未入库），
本次入库并修正了两处过时内容：移除已退役的 Seata 相关 override 与 `SMARTLECT_NACOS_SEATA_ADDR`；
队列数断言不再硬编码 58，改为与导出的 definitions 实际数量比对。
