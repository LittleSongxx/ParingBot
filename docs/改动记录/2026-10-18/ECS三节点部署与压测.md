# ECS 三节点部署与压测

## 需求

提交并推送本轮全部修改，在三节点 ECS 上部署，随后对最常见、最受关注的吞吐/延迟/错误指标做压测，并在发现瓶颈时做可回退的调优。

## 部署

- 本地提交 `d1365cc`，推送 `main`；push CI 通过。
- GitHub Actions `workflow_dispatch` run `39038405815` 完成：backend/assistant/web 通过，node1 部署成功；node2/node3 通过 `sync-app-node.sh` 同步。
- 三节点同一订单 JAR 指纹 `f4c36776411c7a8d8d8e053e46a2289f68a0ade0ec25bf7a20b6e930e30c3b24`；node1 12 进程、node2/node3 各 5 进程健康。
- Flyway 真库：order V7 `order_status_log`、pay V5 `pay_mock_channel_ledger` 成功应用。
- xxl-job 新增 `payDailyReconcile`、`hotStockReconcile`，登记为 18 个任务。
- 部署前补充 `SMARTLECT_MOCK_PAY_SECRET`（未打印/未入库），备份 `runtime.env` 与 order/pay 数据库。
- 部署后 `post_deploy_check.sh` 全部通过；演示账号完成一笔下单/支付/退款 smoke，HMAC、状态历史、渠道流水均正常。

## 压测与调优

- 发压机 node4 `172.17.40.108`（4c8g）；先修复 Docker 与 VPC 路由冲突。
- 浏览链路默认 200 QPS/路由先触发 429；测试限流临时调到 2000，压完恢复 200。
- node2/node3 的 JVM 处理器从 2 调到 4（与 4c8g 匹配），同步写回 `apply-sizing.sh`，避免下次 sync 回退。
- MySQL `max_connections` 从 200 调到 300（`SET PERSIST`，compose 同步改为 300）；压测峰值达到 202，原上限没有余量。
- 冷启动 600 VU（351 QPS/p95 5.2s）已判定无效；充分预热后 600 VU 为 840 QPS/p95 52ms。

## 结果摘要

- 浏览：1200 VU 1512 QPS/p95 540ms；1600 VU 约 1.7k QPS/p95 1.27–1.33s；2000 VU 吞吐平台约 1694 QPS/p95 2.48s。
- 订单（三请求合计）：80 VU 96.7 QPS/p95 136ms；160 VU 168.3 QPS/p95 318ms；240 VU 204.4 QPS/p95 827ms；延迟拐点约 160–240 VU，尚未测得最终吞吐平台。
- node3 是浏览链路热点（1600 VU 时 CPU 99.8%）；Redis/MySQL CPU 不是当前瓶颈。
- 对账脚本 4 项失败已定位为脚本把 `order_status=1` 当已支付、历史迟到支付行和 bootstrap 失败数据；本轮支付成功数与已支付/已完成/已发货/部分退款合计一致。

详见 [ecs-loadtest.md](../../verification/ecs-loadtest.md) 和 `eval/verification/2026-10-18/ecs-loadtest/`。

## 发现与未完成

- 三节点并行重启时 node1 的 admin 曾启动失败，重试后恢复；后续重启改为顺序执行以避免端口/进程竞争。
- node3 的 product/gateway 实例明显慢于 node2，根因尚未定论，未做实例下线或流量重分配。
- 订单链路没有继续上探到平台；MySQL 连接数在 240 VU 达到 202，已提高上限但还需观察长期稳定性。
- 压测限流 2000 只用于测试，生产已恢复 200；不要把测试吞吐当作生产容量。

## 关联版本

部署 commit `d1365cc`；压测环境为同 VPC 三节点 ECS（node1 8c16g，node2/node3 4c8g），单 MySQL。
## 部署后深度排查（2026-10-18）

- **node3 热点**：相同请求量下 node3 product/gateway CPU 约为 node2 的 2–2.5 倍；空闲 `loadCategory` 25ms vs 9ms。直连 MySQL/Redis 只慢 1–5ms，不是单点网络问题。发现公开 `loadCategory` 每请求额外做一次分类查询 + Redis 写快照，仓库中没有快照读取方；已移除公开读路径写入（管理端写操作仍刷新），代码在 `a2bfb19`，本轮重新部署验证。
- **RocketMQ proxy/namesrv OOM**：`rocketmq-proxy` 重启 10 次，23:33:50 被 512MB cgroup OOM 杀掉；`rocketmq-namesrv` 重启 13 次，00:43:04 被 384MB cgroup OOM 杀掉，直接导致第二次 CI 部署 run `39049599672` 的 order 启动失败、站点短暂 502。两者的运行态和 compose 均已提升到 768MB（Xmx384m）；手动恢复后站点 200，复测期间重启计数未再增加。
- **loadgen bootstrap**：旧脚本每个 VU 都执行 `/internal/demo/seed`，160/240 VU 时并发 seed 打满 admin 池并返回 data=null。已改为每进程 seed 一次并显式校验 session；160 VU 复测 0 bootstrap 失败、0 业务错误。
- **对账误报**：旧 `reconcile-loadtest.sh` 把订单/支付/库存按 1:1 比较，且把 `order_status=1` 当全部已支付；修正后按 payOrderId、POST_ORDER 幂等键、订单状态真实粒度比较，23:00–01:30 窗口 8/8 通过。5 笔客户端超时产生的待付款订单已在 15 分钟后收敛为 CLOSED，不混入已付款断言。
- **admin 重启失败**：`apps-down` 约 3 分钟 > `TimeoutStopSec=180`，systemd 强杀 cgroup；三节点 unit 已改为 600 秒并 daemon-reload，重启改为顺序执行。
- **category 热路径**：公开 `loadCategory` 去掉每请求二次分类查询 + Redis 写后，三节点已部署 `a2bfb19` 并预热复测 400 VU：543.6 req/s、p95 176.5ms、p99 563.1ms；不是严格 A/B，但未退化。node3 实例本身仍明显慢于 node2，作为后续替换/迁移项保留。
- **CI 部署异常与复测**：第二次 deploy run `39049599672` 因 namesrv OOM 失败；修复 namesrv 内存后手动恢复。随后 `835d6a8` 的 run `39053891614` 部署成功，三节点健康、部署后探针全过，proxy/namesrv 重启计数保持 10/13。
- 证据：`eval/verification/2026-10-18/ecs-loadtest/{node3-diagnosis,rocketmq-proxy-oom,rocketmq-namesrv-oom,loadgen-bootstrap-fix,reconcile-corrected,admin-restart-timeout,post-catfix-warm-400}.*`。
## 整机重启复核（2026-10-18 02:0x）

- node1 正常恢复，站点 200；node2/node3 应用 unit 因安装的是旧副本 unit（缺少 `ExecStartPre wait-cluster`、`TimeoutStopSec=180`）在 Sentinel 未就绪时失败。
- 已将新 replica unit 写入 `/opt/cluster/app-node` 并安装到 node2/node3，顺序重启后两节点各 5 进程健康；`post_deploy_check.sh` 全部通过。
- Sentinel 在整机重启后将 node2 Redis 提升为 master、node1 成为 slave；这是正常故障转移，应用通过 Sentinel 正常访问。node2 容器旧健康检查固定要求 `role:slave`，因此显示 unhealthy；仓库已改为 PING 检查，运行中容器待下次重建应用，本轮未在 master 节点重建 Redis。
- 重启后核对：限流 200、JVM 4、HMAC 密钥、MySQL 300、proxy/namesrv 768MB、systemd 停止宽限 600s 均保留；未发现新的 OOM。
- 证据：`eval/verification/2026-10-18/ecs-loadtest/reboot-recovery.txt`。
