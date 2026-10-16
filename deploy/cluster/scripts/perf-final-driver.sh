#!/usr/bin/env bash
# 性能表 A/B 全自动驱动（node1 执行）
#
# 一次跑完：解除限流 → 形态 A（单机）阶梯 → 形态 B（集群）阶梯 → 回落限流。
# 每个形态用 tune-benchmark.sh（预热按累计请求数，各变体同一起点）。
#
# 为什么两形态都要重新测：本轮改动（RPC 移出事务、MQ 确认改异步、副本 Redis 地址修正、
# 连接池与 JVM 调整）每一项都影响吞吐与延迟，旧表已不代表当前系统。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODES_ENV=""
for candidate in "$HERE/../nodes.env" /opt/cluster/nodes.env; do
  [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
RT=/opt/smartlect/run/runtime.env
RESULTS=/opt/cluster/evidence/perf-final-$(date +%Y%m%d-%H%M).tsv
LOG=/tmp/perf-final.log

log() { echo "[perf $(date +%T)] $*" | tee -a "$LOG"; }

set_limiter() { # $1=值 或 "prod"（删除覆盖）
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    if [ "$1" = "prod" ]; then
      cmd="sed -i '/^SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=/d' $RT"
    else
      cmd="grep -q '^SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=' $RT && sed -i 's/^SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=.*/SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=$1/' $RT || echo 'SMARTLECT_GATEWAY_RATELIMIT_DEFAULTQPS=$1' >> $RT"
    fi
    if [ "$ip" = "$NODE1_IP" ]; then eval "$cmd"; else ssh $CLUSTER_SSH_OPTS "root@$ip" "$cmd"; fi
  done
  log "限流口径 → $1，重启三节点"
  ( systemctl restart smartlect-apps ) &
  ssh $CLUSTER_SSH_OPTS "root@$NODE2_IP" "systemctl restart smartlect-apps" &
  ssh $CLUSTER_SSH_OPTS "root@$NODE3_IP" "systemctl restart smartlect-apps" &
  wait
  sleep 15
  (cd /opt/smartlect && /usr/bin/python3 scripts/runtime.py apps-check 2>&1 | tail -1)
}

log "=== 性能表重测开始（当前构建） ==="
set_limiter 2000

log "--- 形态 A：单机（撤 nginx upstream + 停 node2/3 副本）---"
bash "$HERE/loadtest-suite.sh" form single 2>&1 | tail -2
bash "$HERE/tune-benchmark.sh" "A-single" "$RESULTS"

log "--- 形态 B：三节点集群（起副本 + 挂三网关 upstream）---"
bash "$HERE/loadtest-suite.sh" form cluster 2>&1 | tail -2
bash "$HERE/tune-benchmark.sh" "B-cluster" "$RESULTS"

log "--- 收尾：限流回落生产值 ---"
set_limiter prod
log "=== 完成，结果在 $RESULTS ==="
column -t -s$'\t' "$RESULTS"
