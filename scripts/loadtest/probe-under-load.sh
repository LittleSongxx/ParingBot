#!/usr/bin/env bash
# 确认负载已起量后再测量（node1 执行）
#
# 为什么需要"确认"：嵌套 ssh + setsid 启动 k6 有启动延迟，直接 sleep 后测量经常
# 落在负载尚未起量（或已结束）的空窗，得出"CPU 3%"、"服务没收到请求"这类假结论。
# 本脚本以"被测服务的请求计数在涨"为唯一判据。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# nodes.env 的位置随部署形态不同（仓库里在 deploy/cluster/，服务器上在 /opt/cluster/）：
# 按优先级逐个探测，避免换个地方跑就 "unbound variable"。
for candidate in "${CLUSTER_NODES_ENV:-}" "$HERE/../../deploy/cluster/nodes.env" \
                 "/opt/cluster/nodes.env" "$HERE/../nodes.env"; do
  [ -n "$candidate" ] && [ -f "$candidate" ] && { NODES_ENV="$candidate"; break; }
done
# shellcheck source=/dev/null
source "$NODES_ENV"
LAUNCHER_IP="${LAUNCHER_IP:-172.17.40.108}"
SSH4="ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 root@$LAUNCHER_IP"
VUS="${1:-1200}"
HOLD="${2:-80}"

cnt() {
  # 集群形态下请求分散在三个 product 实例；只数 node1 会在负载起量后误判“未起量”。
  local total=0 one
  for host in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    one=$(curl -s -m 5 "http://$host:18106/actuator/prometheus" 2>/dev/null \
      | awk '/^http_server_requests_seconds_count/{s+=$2} END{printf "%.0f", s+0}')
    total=$((total + ${one:-0}))
  done
  printf '%s' "$total"
}
metric() { curl -s -m 5 "http://$1:18106/actuator/prometheus" 2>/dev/null | awk -v k="$2" '$1 ~ "^"k"\\{"{printf "%.0f", $2*('"${3:-1}"')}'; }

echo "[probe] 启动 $VUS 并发 × ${HOLD}s"
$SSH4 "cd /root/loadtest && setsid nohup k6 run -e VUS=$VUS -e HOLD=${HOLD}s -e BASE=https://smartlect.cn -e OUT=/tmp/probe-live.json browse-k6.js > /tmp/probe-live.log 2>&1 < /dev/null &" >/dev/null 2>&1

echo "[probe] 等待负载起量（以 node1 商品请求计数增长为判据）…"
prev=$(cnt "$NODE1_IP"); ready=0
for _ in $(seq 1 30); do
  sleep 3
  now=$(cnt "$NODE1_IP")
  if [ "$(( now - prev ))" -gt 60 ]; then ready=1; break; fi
  prev=$now
done
if [ "$ready" -ne 1 ]; then echo "[probe] 负载未起量，终止（检查发压机）"; $SSH4 "tail -3 /tmp/probe-live.log"; exit 1; fi
echo "[probe] 负载已起量 ✓（3 秒内 +$(( now - prev )) 请求）"

echo "[probe] 测量中："
for round in 1 2 3; do
  echo "  --- 第 $round 轮 ---"
  for ip in $NODE1_IP $NODE2_IP $NODE3_IP; do
    a=$(cnt "$ip"); am=$(metric "$ip" hikaricp_connections_active); ap=$(metric "$ip" hikaricp_connections_pending)
    aq=$(metric "$ip" hikaricp_connections_acquire_seconds_max 1000); at=$(metric "$ip" hikaricp_connections_timeout_total)
    sleep 2
    b=$(cnt "$ip")
    printf "    %-16s 请求/2s=%-5s pool active=%-4s 排队=%-4s 等连接max=%-6s 超时=%s\n" \
      "$ip" "$(( b - a ))" "$am" "$ap" "$aq" "$at"
  done
  # 各节点瞬时 CPU（3 秒）
  for spec in "$NODE1_IP 1" "$NODE2_IP 2" "$NODE3_IP 3"; do
    set -- $spec
    if [ "$2" = "1" ]; then
      x=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat); sleep 3; y=$(awk '/^cpu /{print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat); set -- $x $y
      printf "    CPU node1=%.0f%%" "$(awk -v t1=$1 -v i1=$2 -v t2=$3 -v i2=$4 'BEGIN{print 100*(1-(i2-i1)/(t2-t1))}')"
    else
      printf "  node%s=%s%%" "$2" "$(ssh $CLUSTER_SSH_OPTS "root@$1" 'a=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); sleep 3; b=$(awk "/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8, \$5+\$6}" /proc/stat); set -- $a $b; awk -v t1=$1 -v i1=$2 -v t2=$3 -v i2=$4 "BEGIN{printf \"%.0f\", 100*(1-(i2-i1)/(t2-t1))}"')"
    fi
  done
  echo
done
echo "[probe] 负载结果："; $SSH4 "grep '^\[loadgen\]' /tmp/probe-live.log | tail -1"
