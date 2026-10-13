#!/usr/bin/env bash
# 把集群编排分发到 node2/node3（node1 执行），并生成各组件 .env
#
# 前置：deploy/cluster/ 已同步到 node1 的 /opt/cluster/（含本脚本）。
# 分发内容是**无密钥的编排文件**；含密钥的 .env 由 gen-cluster-env.sh 在 node1 生成后单独推送。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[distribute $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

log "generating component .env on node1..."
bash "$HERE/gen-cluster-env.sh"

for n in 2 3; do
  eval "ip=\$NODE${n}_IP"
  log "syncing orchestration to $ip ..."
  remote "$ip" "mkdir -p $CL/{rocketmq,redis,sentinel,nacos,evidence} && chmod 700 $CL/{rocketmq,redis,sentinel,nacos}"
  # 编排文件（无密钥）
  for f in nodes.env rocketmq/compose.c$n.yaml \
           redis/compose.replica.yaml sentinel/compose.sentinel.yaml nacos/compose.cluster.yaml; do
    scp $CLUSTER_SSH_OPTS "$CL/$f" "root@$ip:$CL/$f" >/dev/null
  done
  # 含密钥的 .env（权限 600 随文件走）
  for f in rocketmq/.env redis/.env sentinel/.env nacos/.env; do
    scp $CLUSTER_SSH_OPTS "$CL/$f" "root@$ip:$CL/$f" >/dev/null
  done
  remote "$ip" "chmod 600 $CL/rabbit/.env $CL/redis/.env $CL/sentinel/.env $CL/nacos/.env && echo '  synced'"
done
log "distribution complete"
