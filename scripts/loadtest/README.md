# 压测与测量资产

本目录是**产生负载和测量指标**的全部工具；集群的搭建/运维脚本在 `deploy/cluster/scripts/`
（那里的 `loadtest-suite.sh` 额外负责切换单机/集群形态，所以留在集群侧）。

所有脚本从 `deploy/cluster/nodes.env` 读节点拓扑（可用 `CLUSTER_NODES_ENV` 覆盖）。

## 发压器

| 文件 | 场景 | 说明 |
|---|---|---|
| `browse-k6.js` | 浏览链路（首页 + 分类 + 商品列表） | **主发压器**，k6（Go）。输出 JSON 与 `loadgen.py` 同构，`analyze-knee.py` 通吃 |
| `loadgen.py` | 浏览 / 交易闭环（加购→下单→支付） | Python asyncio 版。**400 并发 TLS 长连接下会把 4 核发压机打满**，浏览场景请用 k6；交易场景并发低（3-10），可用 |
| `browse.js`、`browse-hot.js` | 浏览链路（2026-09 版） | 历史脚本（`browse-hot` 用 ~0.1s 思考时间探 CPU 绝对墙），保留供对照 |
| `assistant-chat.js`、`assistant-control.js`、`loadtest-assistant.sh` | AI 助手链路 | 2026-09 版；chat 的 `ORIGIN` 必须是后端白名单值，否则 100% `origin_denied` |

## 测量与编排

| 文件 | 用途 |
|---|---|
| `tune-benchmark.sh` | **调参基准台**：固定负载（预热 + 浏览阶梯 + 交易闭环），每个参数变体跑同一套并写 `tuning-results.tsv` |
| `deploy/cluster/scripts/loadtest-suite.sh` | 形态 A/B 编排：切换单机/集群形态 + 跑阶梯 + 采证 |
| `analyze-knee.py` | 从阶梯结果算**拐点与峰值**（口径写死在脚本里，可复算） |
| `collect-results.py` | 把证据目录里的 JSON 汇成一张表 |

## 诊断（回答"为什么慢"）

| 文件 | 用途 |
|---|---|
| `hikari-probe.py` | 加载中实时采 Hikari 连接池：池满/排队/等连接时长——判定"假墙"的关键取证 |
| `bottleneck-probe.sh` | 加载中同时采 Redis ops、MySQL 连接数、Tomcat 线程池 |
| `resource-sampler.py` | 轻量 CPU/内存采样（只读 /proc，采样成本可忽略，不引入干扰） |
| `sample-fleet-cpu.sh` | 一次采三节点 CPU |
| `probe-balance.sh` | 加载中测**分流是否均衡**（各网关/各副本的请求增量）+ 各节点瞬时 CPU |
| `probe-replica-latency.sh` | 同一次负载下逐副本的延迟增量——定位"某个副本特别慢" |
| `probe-latency-matrix.sh` | 三台机器 × 三个副本的延迟矩阵——区分"服务本身慢"与"访问路径慢" |
| `thread-dump-summary.py` | 线程栈按卡点聚合（配合 `kill -3 <pid>`），回答"CPU 空闲却慢" |
| `health-review.sh` | 单节点体检：启动时间、错误日志、连接池、线程数、参数与规格是否匹配 |
| `launcher-capacity-probe.sh` | 测**发压机自己**的 CPU，确认没把发压机极限当成被测系统极限 |

## 基准数字

不同轮次的数字口径不同，引用时务必带上条件：

| 条件 | 数字 | 出处 |
|---|---|---|
| 2026-09：8c32g + JVM 三键 + Hikari 12 + 限流 400 | 单机 browse 真极限 815 req/s（CPU 墙）；控制面 30 req/s；对话 12 轮/分钟（信号量 2 成本闸） | 原设计/压测记录已随文档面清理下线，Git 历史可查 |
| 2026-10-05：三节点（8c16g + 2×2c8g）+ 限流解除 | 单机峰值 803.66 req/s @ 600 并发；集群峰值 832.32 req/s @ 1600 并发 | `eval/verification/cluster-loadtest-20261005/`（**该轮测具已被发现口径偏高，见下**） |

## 踩过的坑（新脚本请沿用这里的约束）

1. **业务错误是 HTTP 200 + `{"status":"error"}`**——只看状态码会把失败当成功。
   2026-10-05 就因此把 10 万次参数校验失败当成"零错误"报了出去。两个发压器都已内置业务错误统计。
2. **接口契约要对齐**：`/product/loadProduct` 要 `pageNo`（不是 `page`）、
   `/productCart/add2Cart` 要表单绑定（不是 JSON）。发错参数会让请求在校验层快速失败，
   测出的吞吐是"快速失败的吞吐"，不是真实处理能力。
3. **预热必须够重够久**：20s/120 并发时 JIT 远未完成，首档 p95 会虚高一个数量级
   （实测同配置冷启动 p95 8493ms vs 热态 2184ms）。基准台默认预热 300 并发 × 90s。
4. **先确认发压机不是瓶颈**（`launcher-capacity-probe.sh`）：Python 发压器在 400 并发下
   把 4 核打满 100%，测出的"277 req/s 墙"其实是被测发压机的极限。
5. **测 CPU 要在负载中进行**：负载结束后的采样只反映回落后的空转（曾把 74% 的峰值记成 3%）。
6. **嵌套 ssh + 后台启动有启动延迟**：按时间窗做增量测量必须留余量，
   否则会测到"负载还没起来"的空窗，得出"服务没收到请求"的错误结论。
7. **同一文件只能有一个采样器**：`resource-sampler.py` 以 `"w"` 打开输出文件，
   重复启动会互相截断，数据不可用。
8. 历史坑位：`set -o pipefail` 下 `| head` 会 SIGPIPE 杀脚本（用 `sed -n 1p`）；
   全链路压测前先给旁路系统（Jaeger/日志）设内存上界。

## 复现一次完整测量

```bash
# 1) 切到集群形态并预热+阶梯+采证（node1 执行）
bash deploy/cluster/scripts/loadtest-suite.sh cluster

# 2) 算拐点与峰值
python3 scripts/loadtest/analyze-knee.py /opt/cluster/evidence/loadtest-*/

# 3) 换参数跑对照（基准台自带预热）
bash scripts/loadtest/tune-benchmark.sh "pool=12"
```
