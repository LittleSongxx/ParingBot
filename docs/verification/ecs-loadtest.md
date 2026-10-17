# ECS 三节点压测（2026-10-18）

## 结论

- 浏览链路在测试限流 2000 QPS、副本 JVM 4 处理器、充分预热后：
  - 1200 VU：**1511.9 req/s，p95 539.9ms，p99 1138ms，0 错误**；
  - 1600 VU：**1698–1712 req/s，p95 1273–1330ms**；
  - 2000 VU：**1693.7 req/s，p95 2479.6ms**，吞吐进入平台。
  - 按 p95<1s 的工程口径，可持续观测点约 **1200 VU / 1.51k req/s**；峰值约 **1.7k req/s**。
- 订单闭环（加购 + 下单 + mock 支付，QPS 为三请求合计）到 240 VU 仍未出现吞吐平台：
  - 80 VU：96.7 req/s，p95 135.5ms；
  - 160 VU：168.3 req/s，p95 317.6ms；
  - 240 VU：204.4 req/s，p95 826.6ms，出现 2 个业务错误和少量 bootstrap 失败。
  - 延迟拐点出现在 160–240 VU 之间，但没有足够数据声称订单链路的最终吞吐上限。
- node3 是浏览链路的主要资源热点：1600 VU 期间 node3 CPU 99.8%，node1 约 47%，node2 约 38%；node3 的 product/gateway 进程 CPU 明显高于其它节点。Redis 约 600–670 ops/s（CPU 4–5%），MySQL `Threads_running` 约 2，说明瓶颈不在 Redis/MySQL CPU，而在应用 CPU/实例差异。

## 环境

| 项 | 值 |
|---|---|
| 部署 | 首轮 run `39038405815` / commit `d1365cc`；修复 commit `a2bfb19` 的 CI run `39049599672` 曾因 namesrv OOM 失败并手动恢复；最终 commit `835d6a8` 的 run `39053891614` 部署成功，node1/node2/node3 应用构建一致 |
| 应用 | 9 个 Java 服务 + assistant + 双前端；三节点同 JAR 指纹 |
| 节点 | node1 8c16g；node2/node3 4c8g |
| 发压机 | node4 `172.17.40.108`，4c8g，同 VPC；先修复 Docker `172.17.0.0/16` 与 VPC 路由冲突 |
| 工具 | k6 v0.54.0（浏览）；`scripts/loadtest/loadgen.py`（订单） |
| 数据 | 20 个演示商品 / 40 个 SKU；订单每轮前重置库存；只使用演示账号和 `910000000000` 目录 |
| 限流 | 测试期间 `SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=2000`；结束后恢复 200 |
| JVM | node1 4 处理器/512m；node2/node3 由 2 改为 **4 处理器**/512m（压测调优，已写回 `apply-sizing.sh`） |
| MySQL | `max_connections` 测试前 200，压测中实际 `Max_used_connections=202`；已 `SET PERSIST` 到 **300**，并写回 compose |

## 浏览链路结果

### 生产默认限流（200 QPS/路由）

| VU | 请求数 | QPS | p50 | p95 | p99 | 429/业务错误 |
|---:|---:|---:|---:|---:|---:|---:|
| 400 | 15132 | 458.5 | 12.4ms | 675.5ms | 2376.7ms | 57（0.38%） |
| 800 | 25806 | 600.1 | 10.2ms | 3232.8ms | 4378.4ms | 504（1.95%） |

800 VU 的 600 QPS 正好接近“三条读路由 × 200 QPS”，先撞到限流，不是后端容量。

### 抬高限流后的有效曲线（充分预热 + 副本 JVM 4）

| VU | 请求数 | QPS | p50 | p95 | p99 | 错误 |
|---:|---:|---:|---:|---:|---:|---:|
| 600 | 52920 | 840.3 | 9.2ms | 51.9ms | 222.3ms | 0 |
| 800 | 70935 | 1127.5 | 9.0ms | 30.6ms | 245.7ms | 0 |
| 1200 | 95169 | 1511.9 | 9.0ms | 539.9ms | 1138.0ms | 0 |
| 1600 | 106983 | 1698.1 | 9.0ms | 1273.2ms | 1816.2ms | 0 |
| 1600（资源采样轮） | 107889 | 1712.5 | 9.0ms | 1330.0ms | 2022.8ms | 0 |
| 2000 | 106707 | 1693.7 | 9.5ms | 2479.6ms | 3329.2ms | 0 |

低负载基线取 200 VU 的 p95=48.5ms；按 p95≥2 倍基线约 97ms 计算，延迟拐点首次出现在 **1200 VU**；吞吐在 **1600→2000 VU** 基本持平，吞吐拐点约 **2000 VU**。600/800 VU 的 p95 反而低于 400 VU，是缓存/预热/JIT 的共同结果，不能把这条曲线当成严格单调。

### 资源采样

- 1600 VU（约 35 秒采样）：node1 CPU 46–49%、node2 35–42%、**node3 99.8%**；node3 load average 21–23。
- 600 VU：node3 product 约 151% CPU（4 核折算）、gateway 约 80%；node1/node2 约 25–34%。
- Redis：600–670 ops/s、CPU 约 4–5%；MySQL：`Threads_connected=86`、`Threads_running=2`（1600 VU 采样）。
- 结论：当前浏览链路的显著热点是 **node3 的 product/gateway**，不是 Redis 或 MySQL CPU。node3 的 product 累计平均请求耗时也高于 node2（loadCategory 约 52ms vs 7ms），具体是实例 CPU 配额、JVM/GC 还是流量分布仍需进一步定位；本轮不把单节点热点误写成全局极限。

## 订单链路结果

| VU | QPS（三请求合计） | p50 | p95 | p99 | 业务错误 | 传输错误 |
|---:|---:|---:|---:|---:|---:|---:|
| 3（预热） | 3.8 | 54.5ms | 169.7ms | 963.3ms | 0 | 0 |
| 10 | 13.5 | 46.0ms | 130.6ms | 159.0ms | 0 | 0 |
| 20 | 26.5 | 40.6ms | 116.1ms | 139.4ms | 0 | 0 |
| 40 | 52.0 | 39.2ms | 122.5ms | 165.5ms | 1（0.03%） | 0 |
| 80 | 96.7 | 36.4ms | 135.5ms | 259.9ms | 0 | 0 |
| 160 | 168.3 | 66.1ms | 317.6ms | 495.5ms | 0 | 0.07% |
| 240 | 204.4 | 147.7ms | 826.6ms | 1404.9ms | 2（0.02%） | 0.02% |

240 VU 的 `postOrder` p95 为 1110ms、`add2Cart` 612ms、`payComplete` 275ms。订单链路仍未进入吞吐平台，但 160→240 VU 的延迟增长已经明显，只能把拐点标在 **160–240 VU** 区间。

### 压测后对账

旧版 `reconcile-loadtest.sh` 的 4 项失败已定位为**脚本口径错误**，不是订单/支付不一致：

- 脚本把订单数、支付单数、库存记录数按 1:1 比较；实际一笔下单命令可以生成多个子单，同一个 `payOrderId` 只对应一笔支付/一次 `ORDER_DEDUCT`。
- 库存账本还包含 `ORDER_CLOSE_RESTORE` / `REFUND_RESTORE`，幂等账本还包含退款/取消命令。
- 脚本只把 `order_status=1` 当已支付；实际应包含已发货/已完成/部分退款，并排除仍在 15 分钟关单窗口的 `WAIT_PAYMENT`。

修正后的脚本按 `payOrderId`、`POST_ORDER` 幂等键和订单状态真实粒度比较，窗口 `2026-10-17 23:00:00 ~ 2026-10-18 01:30:00` 的结果：

```text
orders=14545  distinct_pay_ids=14537  pay_trades=14537
post_keys=14543  post_completed=14538  order_deducts=14538
paid_pay_ids=14537  settled_trades=14537
orders_without_pay=0  orders_without_deduct=0  items=14547  item_orphans=0
通过 8 项，失败 0 项
```

后续 seedfix 的 160 VU 测试在 00:24 产生了 5 笔 `WAIT_PAYMENT` 订单（客户端在提交后未完成支付），已在 15 分钟超时后收敛为 `CLOSED`；修正脚本用已付款状态集合比较，待付款/已关闭订单不参与支付和库存断言。没有发现新的支付/库存系统性不一致。

## 深度排查（2026-10-18 补充）

### node3 性能热点

400 VU、30 秒、三节点 product 请求增量近似相等（各约 1913）时：

| 节点 | product CPU | gateway CPU | 空闲 loadCategory |
|---|---:|---:|---:|
| node1（8c） | 96.5% | 57.0% | — |
| node2（4c） | 96.6% | 50.0% | 8–10ms |
| node3（4c） | **247.9%** | **179.2%** | **15–34ms** |

- node2/node3 是同一实例规格、同一 JDK/JAR、`ActiveProcessorCount=4`；node3 没有 CPU steal，cgroup 也没有配额限制。
- node3 直连 MySQL 仅比 node2 慢 1ms，Redis PING 慢 1–5ms；Hikari 出现 acquire 216ms/usage 167ms，说明 node3 的应用侧等待和 CPU 都更重。
- 发现公开 `loadCategory` 每个请求都会重新查一次分类表并写 Redis 快照，而仓库中没有这个快照的读取方；这属于热路径浪费。已移除公开读路径的 Redis 写入，保留管理端分类写操作的刷新。node3 的实例级差异仍未完全定论，不能简单归因于这一处。

### RocketMQ proxy OOM

- `docker inspect rocketmq-proxy` 显示重启 **10 次**；`dmesg` 在 2026-10-17 23:33:50 记录该容器 cgroup OOM，被杀 Java 进程 RSS 约 490MB。
- 容器原内存上限 512MB，`JAVA_OPT_EXT=-Xms256m -Xmx256m`，gRPC/Netty native 内存没有余量。
- 已把运行态内存上限调到 768MB，并把 compose 的 `mem_limit` 改为 768m、堆上限改为 384m；proxy 端口和健康检查正常。该问题会放大下单/支付事件延迟，但本轮没有把它当成唯一的订单延迟原因。

### loadgen bootstrap 失败

- 旧 loadgen 在每个 VU 的 bootstrap 中调用 `/internal/demo/seed`（100 用户 + 20 商品的写事务）。160/240 VU 时大量 seed 并发，session 返回 `data=null`，报 `'NoneType' object is not subscriptable`。
- 已改为每个 worker 起 VU 前只 seed 一次，并对 session 的 success/data 做显式校验；库存重置到每 SKU 500 后，160 VU/30 秒复测 **0 bootstrap 失败、0 业务错误**。

### node1 admin 重启失败

- 并行重启时 `apps-down` 逐个停止 9 个 Java 服务约耗时 3 分钟，正好撞上 systemd `TimeoutStopSec=180`；systemd 强杀整个 cgroup，下一次启动 admin 出现半清理状态。
- 已把 node1 和副本的 unit 停止宽限从 180 秒提高到 600 秒，三节点已安装并 `daemon-reload`；后续重启改为顺序执行。

## 调优动作

1. **网关限流**：先确认 200 QPS/路由会造成 429；测试期调到 2000，测试后恢复 200。生产默认值不变。
2. **副本 JVM**：node2/node3 从 2 处理器改为 4，和 4c8g 机器规格一致；`apply-sizing.sh` 已写回，避免下次同步回退。
3. **MySQL 连接上限**：200→300，`SET PERSIST` 持久化，compose 同步改为 300；压测实测峰值 202，原 200 上限没有安全余量。
4. **预热**：600 VU 冷启动测得 351 QPS/p95 5.2s，预热后同档 840 QPS/p95 52ms；冷启动数据已标记无效，不能和热态混比。
5. **node3 热点**：已记录 product/gateway CPU 与请求耗时差异，未在本轮做实例下线或流量重分配；这是下一轮需要单独定位的运维/容量问题。

## 修复后的验证

- commit `a2bfb19` 去掉公开 `loadCategory` 的二次分类查询 + Redis 写后，三节点同步完成；预热后 400 VU/60 秒复测：**543.6 req/s，p95 176.5ms，p99 563.1ms，429 0.15%**。这不是严格 A/B（此前 400 VU 是 30 秒轮次），但说明热路径写入已移除后没有退化。
- `rocketmq-proxy`、`rocketmq-namesrv` 运行态内存均提升到 768MB，复测期间重启计数分别停留在 10/13，没有再增加。
- systemd `TimeoutStopSec=600` 已在三节点安装；部署后的 `post_deploy_check.sh` 全部通过，站点 200。
- 修正后的对账脚本在 23:00–00:10 窗口 8/8 通过；5 笔 seedfix 产生的待付款订单处于 15 分钟关单窗口，未计入一致性断言。

## 原始证据

目录：`eval/verification/2026-10-18/ecs-loadtest/`

- `ecs-baseline-*.json`：默认 200 限流基线；
- `ecs-cpu4-warm-*.json`：JVM 4 + 预热后的有效浏览曲线；
- `ecs-rl2000-*.json`：限流抬高后、调优前的过渡数据（其中 800 VU 是冷/拥塞无效档）；
- `ecs-cpu4-600.json`：JVM 重启后的冷态无效对照；
- `ecs-order-*.json`：订单闭环各档；
- `fleet-*.out`、`bottleneck-1600.txt`：三节点 CPU、Redis、MySQL 采样；
- `post-deploy-final.txt`、`ecs-demo-final.json`：部署后探针与最终交易 smoke；
- `reconcile-after-order.txt`：旧脚本的原始误报输出；
- `reconcile-corrected.txt`：修正后 8/8 通过；
- `node3-diagnosis.txt`、`rocketmq-proxy-oom.txt`、`admin-restart-timeout.txt`、`loadgen-bootstrap-fix.txt`：深度排查证据；
- `ecs-order-seedfix-*.json`：seed 修复后的订单复测；
- `post-catfix-warm-400.json`：category 热路径修复后的 400 VU 预热复测；
- `rocketmq-namesrv-oom.txt`、`post-deploy-after-fix.txt`：namesrv OOM 与修复后部署核对。

## 限制

- 发压机是 4c8g；浏览 1600/2000 VU 时需继续监控发压机 CPU，超过 70% 的档位不可当容量结论（本轮采集时发压机空闲，订单 240 VU 的 Python 发压器未出现明显 CPU 饱和）。
- node3 的实例级差异仍未彻底定位；本轮没有把 node3 下线或重分配流量，避免用“隐藏坏节点”换取表面吞吐。
- 这是同 VPC、单 MySQL、三节点应用的实验环境，不是生产 SLO；没有做多地域、故障切换、长时间 soak。
- 600/800 VU p95 优于 400 VU 反映了预热和缓存效应；曲线不是严格单调，峰值/拐点只作为该环境下的观测值。
