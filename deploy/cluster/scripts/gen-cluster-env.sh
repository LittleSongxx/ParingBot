#!/usr/bin/env bash
# 渲染集群各组件 .env（node1 执行，只生成一次，重跑保持稳定）
#
# 为什么把密钥和拓扑写进同一个 .env：compose 的 --env-file 会**取代**默认 .env 查找，
# 一个文件同时携带组件密钥与节点 IP，远端只需分发一份，避免两处 env 不同步。
# 密钥来源是 node1 的 run/runtime.env（单机期就已存在），不新增任何凭据文件。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
SRC="${RUNTIME_ENV:-/opt/smartlect/run/runtime.env}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"

get() { grep -oP "^$1=\K.*" "$SRC" | head -1; }

mkdir -p "$CL"/{rocketmq,nacos,redis,sentinel,evidence}
chmod 700 "$CL"/{rocketmq,nacos,redis,sentinel}

topology() {
  cat <<EOF
NODE1_IP=$NODE1_IP
NODE2_IP=$NODE2_IP
NODE3_IP=$NODE3_IP
NODE1_NAME=$NODE1_NAME
NODE2_NAME=$NODE2_NAME
NODE3_NAME=$NODE3_NAME
ROCKETMQ_NAMESRV_PORT=$ROCKETMQ_NAMESRV_PORT
ROCKETMQ_BROKER_PORT=$ROCKETMQ_BROKER_PORT
ROCKETMQ_DLEDGER_PORT=$ROCKETMQ_DLEDGER_PORT
ROCKETMQ_GRPC_PORT=$ROCKETMQ_GRPC_PORT
REDIS_PORT=$REDIS_PORT
SENTINEL_PORT=$SENTINEL_PORT
NACOS_PORT=$NACOS_PORT
EOF
}

umask 177
topology > "$CL/rocketmq/.env"

{ topology
  echo "NACOS_AUTH_TOKEN=$(get SMARTLECT_NACOS_AUTH_TOKEN)"
  echo "NACOS_IDENTITY=$(get SMARTLECT_NACOS_IDENTITY)"
  echo "NACOS_MYSQL_PASSWORD=$(get SMARTLECT_NACOS_MYSQL_PASSWORD)"
  echo "MYSQL_HOST_PORT=$(get SMARTLECT_MYSQL_PORT)"
} > "$CL/nacos/.env"

REDIS_PW=$(get SMARTLECT_REDIS_PASSWORD)
for d in redis sentinel; do
  { topology; echo "REDIS_PASSWORD=$REDIS_PW"; } > "$CL/$d/.env"
done

echo "cluster env rendered: rocketmq/nacos/redis/sentinel (.env, mode 600)"
