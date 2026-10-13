#!/usr/bin/env bash
# 集群终态验证 + 证据采集（node1 执行；只读，不改任何状态）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
EV="$CL/evidence"
mkdir -p "$EV"
log() { echo "[verify $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }
NAMESRV_PORT="${ROCKETMQ_NAMESRV_PORT:-9876}"

log "== RocketMQ =="
docker exec rocketmq-broker sh mqadmin clusterList -n 127.0.0.1:$NAMESRV_PORT > "$EV/rocketmq-cluster-list.txt"
REPLICAS=$(grep -c "^broker-a" "$EV/rocketmq-cluster-list.txt" || true)
[ "$REPLICAS" -ge 3 ] || { echo "expect 3 dledger replicas, got $REPLICAS"; exit 1; }
echo "dledger replicas: $REPLICAS"
docker exec rocketmq-broker sh mqadmin consumerProgress -n 127.0.0.1:$NAMESRV_PORT -g G_smartlect_pay_success > "$EV/rocketmq-consumer-progress.txt" 2>/dev/null || true
echo "consumer progress sampled: $(head -3 "$EV/rocketmq-consumer-progress.txt" | tr '\n' ' ')"

log "== Redis =="
PW=$(grep -oP '^REDIS_PASSWORD=\K.*' "$CL/sentinel/.env")
docker exec smartlect-redis-1 redis-cli -a "$PW" --no-auth-warning info replication \
  | grep -E '^(role|connected_slaves|slave[0-9])' | tee "$EV/redis-replication.txt"
for ip in "$NODE2_IP" "$NODE3_IP"; do
  echo "-- replica $ip --" >> "$EV/redis-replication.txt"
  remote "$ip" "docker exec redis-replica redis-cli -a '$PW' --no-auth-warning info replication | grep -E '^(role|master_host|master_link_status)'" >> "$EV/redis-replication.txt"
done
cat "$EV/redis-replication.txt"
docker exec redis-sentinel redis-cli -p "$SENTINEL_PORT" sentinel master mymaster \
  | grep -E '^(ip|port|flags|num-slaves|num-other-sentinels|down-after)' | tee -a "$EV/redis-replication.txt"

log "== Nacos =="
{
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    printf "%s readiness: " "$ip"; curl -s -m 3 "http://$ip:8848/nacos/v1/console/health/readiness" || echo -n "(unreachable)"; echo
  done
} | tee "$EV/nacos-readiness.txt"

log "== 应用侧 =="
if [ -d /opt/smartlect ]; then
  (cd /opt/smartlect && /usr/bin/python3 scripts/runtime.py apps-check 2>&1 | tail -5) | tee "$EV/apps-check.txt" || true
fi
log "evidence saved to $EV"
