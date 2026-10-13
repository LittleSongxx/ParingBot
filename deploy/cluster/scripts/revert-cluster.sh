#!/usr/bin/env bash
# 回退到单机形态（node1 执行）：停集群成员 → 撤 override → 恢复旧容器 → 还原 env → 应用门禁
#
# 前提：应用已停或可重启。中间件的**数据卷全部保留**（单机卷 smartlect_rocketmq-store/redis 未被改动，
# 集群成员用的是集群期新卷），所以回退不丢单机期数据。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
RT="${RUNTIME_ENV:-/opt/smartlect/run/runtime.env}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[revert $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

log "0) stopping apps..."
systemctl stop smartlect-apps || true

log "1) restoring runtime.env from pre-cluster backup..."
if [ -f "$RT.pre-cluster" ]; then
  cp "$RT.pre-cluster" "$RT"; chmod 600 "$RT"
  log "   runtime.env restored"
else
  log "   WARNING: $RT.pre-cluster not found; strip cluster keys manually"
fi

log "2) tearing down cluster members on all nodes..."
cd "$CL/rocketmq" && docker compose -f compose.c1.yaml --env-file .env down --volumes || true
cd "$CL/sentinel" && SENTINEL_CONF_DIR=conf-node1 docker compose -f compose.sentinel.yaml --env-file .env down || true
cd "$CL/nacos" && NACOS_NODE_NAME="$NODE1_NAME" NACOS_NODE_SLOT=1 docker compose -f compose.cluster.yaml --env-file .env down || true
for n in 2 3; do
  eval "ip=\$NODE${n}_IP"; eval "name=\$NODE${n}_NAME"
  remote "$ip" "cd $CL/rocketmq && docker compose -f compose.c$n.yaml --env-file .env down --volumes 2>/dev/null;
    cd $CL/redis && docker compose -f compose.replica.yaml --env-file .env down 2>/dev/null;
    cd $CL/sentinel && SENTINEL_CONF_DIR=conf-node$n docker compose -f compose.sentinel.yaml --env-file .env down 2>/dev/null;
    cd $CL/nacos && NACOS_NODE_NAME=$name NACOS_NODE_SLOT=$n docker compose -f compose.cluster.yaml --env-file .env down 2>/dev/null;
    echo cleaned $ip" || true
done

log "3) restoring single-node middleware..."
# 先撤 override 再起：单机 rocketmq 要占用 8081/9876/10911，必须等集群容器退出
cd /opt/smartlect/deploy
docker compose -p smartlect --env-file "$RT" -f compose.yaml up -d --wait --wait-timeout 240
# 单机 nacos 与集群成员曾共用 smartlect_nacos 库：此处单独拉起 standalone 实例
log "4) starting apps + gate..."
systemctl start smartlect-apps
sleep 20
cd /opt/smartlect && /usr/bin/python3 scripts/runtime.py apps-check
log "REVERT COMPLETE (single-node form restored)"
