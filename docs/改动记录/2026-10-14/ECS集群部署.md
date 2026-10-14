# ECS 三节点集群部署（中间件栈切换后首次上线）

日期：2026-10-14。对象：smartlect.cn 生产三节点（node1 39.96.202.14=172.21.131.151 8c14G；
node2/3 = 172.19.34.202/203 4c）。部署内容：IK + RocketMQ 5.3 + Dubbo 3.3 三批次改造
（b3cca6b..a3380b3 + 部署修复链），**这是批次三 Dubbo 首次跑通全链路的环境**。

## 部署形态（最终）

- node1：全套中间件（MySQL 主/Redis 主+哨兵/ES(IK 自建镜像)/Qdrant/Canal(rocketMQ 模式)/
  xxl-job/Nacos c1）+ **RocketMQ 单机三容器（host 网络，/opt/cluster/rocketmq/compose.single-node1.yaml）**
  + 12 应用进程（systemd smartlect-apps）。
- node2/3：Redis 副本+哨兵、Nacos c2/c3（原有集群中间件保留）；应用副本**已分发未启用**
  （见未完成项）。
- 代码分发：git bundle（/opt/releases）→ /opt/smartlect 服务器构建（mvn+venv+vite）。

## 上线过程中修复的部署缺陷（全部已提交进仓库）

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | 服务器全新构建暴露本地增量编译盲区（IT 测试 5 参调用残留） | b359a3e |
| 2 | canal 依赖 compose 内 namesrv（集群态 host 网络下 invalid） | 去 depends_on，startup.sh 等待循环兜底 |
| 3 | gen-cluster-env.sh 残留 rabbitmq cookie 骨架语法错误 | 清除 |
| 4 | rocketmq-topic-init 跨 profile 依赖弄挂任意不带 profile 的 compose 命令 | proxy 去该依赖 |
| 5 | DLedger：peers 主机名在克隆机上不可解析 / node1 ssh 自身无密钥 / broker 无 -n 不注册 / 卷权限 NPE / mqadmin 内嵌被 OOM(137) / proxy 单节点先起建系统 topic 循环重启 | 全链修复（IP peers、本地执行、-n、user:0+store 路径、独立容器 mqadmin、两阶段拉起）|
| 6 | 单机 proxy 端口只绑 127.0.0.1，跨机与内网探活 refused | cluster override 叠加内网绑定 |
| 7 | xxl-job 只绑 127.0.0.1，副本执行器连不上 | 同上叠加 |
| 8 | Dubbo 严格序列化拒绝 ResponseVO/PaginationResultVO；注册 IP 选中 docker0 网桥 | 补 Serializable + protocol.host 显式引用注册 IP |
| 9 | 应用健康超时不可配（副本首启慢） | SMARTLECT_APP_HEALTH_TIMEOUT_SECONDS（含一次作用域笔误修复） |

## 验证（全部线上真实链路，smartlect.cn）

- 12 进程健康、启动冒烟通过；21 个 MQ 消费者按新拓扑启动；Dubbo provider 注册 IP 正确
  （172.21.131.151/各机内网）。
- **批次三 Dubbo 全链路（本机 WSL2 未通、Linux 一次通过）**：线上登录→下单（order 经
  Dubbo 调 user/stock/product/pay）成功。
- **批次二 RocketMQ 全链路**：下单→Outbox 定时消息 SENT（pay-timeout-close 15 分钟任意
  精度）→mock 支付→pay-success 事件消费→订单 PAID→logistics-step 1 小时定时链到期消费→
  **订单 SHIPPED**（order_status=2）——完整闭环。
- **IK**：线上 ES 以自建 IK 镜像运行，两个索引重建为 ik_max_word（线上商品库为真实 67 个
  演示商品，非本地开发库的 8.7 万种子）。
- 前端双端 https 200。

## 未完成项（如实记录）

1. **DLedger 三副本未启用**：三 broker+namesrv+proxy 全部就绪、topic 预建成功，但 proxy 在
   多数派下启动时「create system broadcast topic DefaultHeartBeatSyncerTopic failed」循环
   重启（单节点孤岛时反而正常）。已收敛为 node1 单机 RocketMQ（已知限制：MQ 单点）。
   排查方向：5.3.2 DLedger+proxy 的系统 topic 创建路径/`lockInStrictMode`。
2. **node2/3 应用副本未启用**：分发完成、user 服务健康通过、product 启动 22.9s 正常且
   Dubbo 注册正确，但 actuator/health 整体 DOWN（readiness/liveness 均 UP，组外某
   indicator 待定位——嫌疑 xxl/sentinel/跨网组件）。已停用避免反复重启；排查方向：
   show-components 定位 DOWN 组件。
3. 线上 DNS/证书等原有设施未动；前端 dist 为服务器构建产物。

## 启用与回滚

- 回滚整体：`git revert` 至 543e4ac（批次改造前）→ 服务器 rebuild+redeploy + 
  `docker start rabbit-c1/c2/c3`（RabbitMQ 集群容器保留未删）+ compose 恢复 rabbitmq 服务。
- 运行时 env 快照：/opt/smartlect/run/runtime.env.pre-cluster 与 .pre-switch。

## 关联代码版本

main 分支至本文件同日 commit；服务器 /opt/smartlect 同步至同一提交。
