# 订单链路压测证据（2026-10-17，本地单机）

## 口径

- 环境：WSL2 单机，MySQL/Redis/RocketMQ/Nacos 等容器本机运行，9 个 Java 服务与前端同机；不是集群，也不是生产容量测试。
- 发压：`scripts/loadtest/loadgen.py order`，每个 VU 循环「加购 → 下单 → mock 支付完成」，思考时间 1–3 秒。
- 轮次：10 VU / 20 VU 各 30 秒；20 VU 时发压器自动用 2 个进程。
- 数据：每次开跑前把 40 个演示 SKU（20 个商品 × 2 规格）统一重置为 500 件；热点库存开启轮额外清空 `smartlect:stock:hot:*` 并配置这 40 个 SKU。
- 业务错误口径：HTTP 200 且 `status=error` 也记为失败；下表四轮均为 0。
- 原始 JSON（包含分接口 p50/p95/p99、状态码、错误分类）：`eval/verification/2026-10-17/order-load/`。

## 结果

| 轮次 | VU | 请求数 | QPS | p50 | p95 | p99 | 最大 | 业务错误 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 热点库存关 | 10 | 426 | 13.1 | 24.62 ms | 67.60 ms | 119.51 ms | 147.85 ms | 0 |
| 热点库存关 | 20 | 816 | 24.83 | 20.67 ms | 57.27 ms | 186.08 ms | 270.89 ms | 0 |
| 热点库存开 | 10 | 429 | 13.05 | 22.19 ms | 60.91 ms | 146.00 ms | 177.12 ms | 0 |
| 热点库存开 | 20 | 816 | 24.94 | 19.48 ms | 61.85 ms | 183.16 ms | 265.25 ms | 0 |

四轮状态码均为 200，传输层错误 0。

## 怎么读

- **这是低并发下的回归信号，不是容量结论。** 10/20 VU 只有约 13/25 QPS，远未压到库存行锁或数据库连接池的瓶颈；不能据此宣称热点库存提升了吞吐。
- **热点库存开/关的差异在噪声范围内。** 20 VU 下 p95 从 57.27 ms 到 61.85 ms、QPS 从 24.83 到 24.94；多出的 Redis/Lua 往返没有在这个并发级别带来收益。原型的价值是验证「Redis 预占 → DB 条件更新 → 释放/提交」的正确性和默认关闭不影响原路径，而不是性能证明。
- **库存守恒已验证。** 20 VU 热点库存轮结束后 40 个 SKU 总库存为 19728；轮次共 272 个成功订单（816 请求 ÷ 3），20000 − 272 = 19728。没有超卖，也没有少卖。
- 首轮 10 VU 曾因 `/internal/product/listOnSaleProductIds` 全量返回 8.7 万条在售 ID，在 10 个并发夹具下打满商品服务 4 连接池并触发堆内存压力；已改为按演示前缀查询（`productIdPrefix=910000000000`），失败轮不计入上表。

## 复跑

```bash
# 以本地实际端口为准（run/runtime.env）
python3 scripts/loadtest/loadgen.py order \
  --base http://127.0.0.1:18082 \
  --admin http://127.0.0.1:18101 \
  --product http://127.0.0.1:18106 \
  --stock http://127.0.0.1:18108 \
  --pay http://127.0.0.1:18103 \
  --vus 10 --hold 30 --think-min 1 --think-max 3 \
  --max-orders 200 --secrets run/runtime.env \
  --json eval/verification/2026-10-17/order-load/hot-off-10vu.json \
  --label hot-off-10vu
```

热点库存轮先在 `run/runtime.env` 设置：

```bash
SMARTLECT_HOT_STOCK_ENABLED=true
SMARTLECT_HOT_STOCK_SKUS=productId:hash,productId:hash,...
```

重启 stock 服务，并清空 `smartlect:stock:hot:*`（或等对账在无活跃预占时按 DB 重建）。跑完恢复 `SMARTLECT_HOT_STOCK_ENABLED=false`。
