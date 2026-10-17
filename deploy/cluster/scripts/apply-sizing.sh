#!/usr/bin/env bash
# 按机器角色与规格设置 JVM / 连接池参数（在每台应用节点各自执行）
#
# 规则不是拍脑袋，是"只改有证据的部分"：
#   · 连接池：所有节点统一 8。证据——order 服务出现 hikaricp acquire 超时 5000ms、
#     单连接被占用 18.1s、超时累计 34 次，并连带 68 次支付成功处理失败与 101 次
#     Outbox 投递失败。原值 4 不够用。
#   · 副本节点的 JVM：PROCESSORS 1→2、XMX 320m→512m。证据——这两个节点是 2026-10-05
#     从 2c8g 升到 4c8g 的，参数还停在 2 核时代；而它们正是压测暴露出的瓶颈
#     （load average 7.2 / 2 核）。参数跟着规格走，避免下次改配置再漂移。
#   · 主节点的 JVM：**不动**。证据——8 核实测 CPU 均值 24.7%/峰值 71.3%、无 OOM、
#     无 GC 告警。没有证据就不改，避免"顺手调参"引入新变量。
#
# 用法：bash apply-sizing.sh [--dry-run]
set -euo pipefail
RT="${RUNTIME_ENV:-/opt/smartlect/run/runtime.env}"
DRY="${1:-}"

# 连接池：实测 1200 并发下 product 池 8 条被打满——active 7/8、185 个请求排队、
# 等连接最长 1494ms，这正是单机天花板的约束（同一形态 2026-09 出现过：池 4→12 让
# 真极限从 605 涨到 815）。提到 16。
#
# 预算：node1 跑 9 个 Java 服务，9 × 16 = 144，加 nacos/assistant ≈ 20 → 164 < 200 ✓
# 注意：若恢复三节点（node2/3 各再跑 4 个服务），17 × 16 = 272 会超过 max_connections=200，
# 那时候要么把池降到 11，要么把 MySQL 的 max_connections 提到 400（deploy/compose.yaml）。
POOL="${SMARTLECT_TUNE_POOL:-16}"

set_env() {
  local key="$1" value="$2"
  if [ "$DRY" = "--dry-run" ]; then printf "  [dry-run] %s=%s\n" "$key" "$value"; return; fi
  if grep -q "^${key}=" "$RT"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$RT"
  else
    echo "${key}=${value}" >> "$RT"
  fi
}

# 副本节点靠 SMARTLECT_APP_SERVICES 识别（主节点不设这个键，跑全部服务）
IS_REPLICA=$(grep -c "^SMARTLECT_APP_SERVICES=" "$RT" || true)

echo "[$(hostname)] $(nproc) 核 / $(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo)G 角色=$([ "$IS_REPLICA" -gt 0 ] && echo 副本 || echo 主节点)"

set_env SMARTLECT_DB_POOL_MAX_SIZE "$POOL"

if [ "$IS_REPLICA" -gt 0 ]; then
  # 副本节点现在是 4c8g；2 处理器是 2c 时代的遗留。2026-10-18 ECS 压测把副本
  # 从 2 调到 4 后，600/800 VU 的浏览吞吐明显改善；按机器规格设置，避免 sync 回退。
  set_env SMARTLECT_JAVA_PROCESSORS "${SMARTLECT_TUNE_REPLICA_PROCESSORS:-4}"
  set_env SMARTLECT_JAVA_XMS 256m
  set_env SMARTLECT_JAVA_XMX 512m
else
  # 主节点同样要设：早先这里"无证据不改"是错的——实测把默认的 2 处理器/256m
  # 提到 4 处理器/512m 后，**单机天花板从 833 提到 1090 req/s（+31%）**，
  # 1200 并发档 p95 从 1863ms 降到 1081ms。JIT 编译线程与 GC 线程按 8 核的
  # 1/9 分摊远不够用，这是 2026-09 记录里就列为"下一排杠杆"的那一项。
  set_env SMARTLECT_JAVA_PROCESSORS "${SMARTLECT_TUNE_PROCESSORS:-4}"
  set_env SMARTLECT_JAVA_XMS 256m
  set_env SMARTLECT_JAVA_XMX "${SMARTLECT_TUNE_XMX:-512m}"
fi

[ "$DRY" = "--dry-run" ] || { chmod 600 "$RT"; echo "  已写入 $RT（生效需 systemctl restart smartlect-apps）"; }
