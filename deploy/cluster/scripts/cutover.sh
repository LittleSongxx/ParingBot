#!/usr/bin/env bash
# 维护窗口：单机形态 → 集群形态（node1 执行）
#
# 顺序刻意如此：
#   先建集群中间件 → 再改 runtime.env → 最后起应用。
#   反过来先改 env 会出现"应用连不上还没建好的集群"的必然失败窗口。
#
# 数据安全性：单机期的数据卷（mysql/rocketmq-store/redis）全程不动；RocketMQ 成员用集群期新卷，
# 拓扑走 defs 导入；redis 容器只是重建（卷复用，会话不丢）。
# 回退：bash revert-cluster.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
ROOT="${SMARTLECT_ROOT:-/opt/smartlect}"
RT="$ROOT/run/runtime.env"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[cutover $(date +%T)] $*"; }

log "0) stopping apps..."
systemctl stop smartlect-apps || true

log "1) applying infra override (mysql/redis 内网绑定)..."
cp -p "$RT" "$RT.pre-cluster"
cd "$ROOT/deploy"
set -a; source "$CL/nodes.env"; set +a
docker compose -p smartlect --env-file "$RT" \
  -f compose.yaml -f "$CL/compose.node1.yaml" up -d --wait --wait-timeout 300

log "2) building rocketmq dledger 3-replica cluster..."
bash "$CL/scripts/build-rocketmq.sh"

log "3) building redis replicas + sentinels..."
bash "$CL/scripts/build-redis.sh"

log "4) building nacos 3-node cluster..."
bash "$CL/scripts/build-nacos.sh"

log "5) switching runtime.env to cluster endpoints + LAN binding..."
/usr/bin/python3 - "$RT" "$NODE1_IP" "$NODE2_IP" "$NODE3_IP" <<'PY'
import sys
path, n1, n2, n3 = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# 集群形态的连接串：Java 走 addresses/sentinel/多地址，assistant 走单端点。
# 应用侧同时打开 LAN 绑定与真实注册 IP —— 这是副本能互相发现的前提。
updates = {
    "SMARTLECT_CLUSTER_FORM": "cluster",
    "SMARTLECT_MYSQL_HOST": n1,
    "SMARTLECT_ROCKETMQ_ENDPOINTS": f"{n1}:8081,{n2}:8081,{n3}:8081",
    "SMARTLECT_CANAL_ROCKETMQ_NAMESRV": f"{n1}:9876",
    "SMARTLECT_NACOS_ADDR": f"{n1}:8848,{n2}:8848,{n3}:8848",

    "SPRING_DATA_REDIS_SENTINEL_MASTER": "mymaster",
    "SPRING_DATA_REDIS_SENTINEL_NODES": f"{n1}:26379,{n2}:26379,{n3}:26379",
    "SMARTLECT_APP_BIND_ADDRESS": "0.0.0.0",
    "SMARTLECT_APP_REGISTER_IP": n1,
    "SMARTLECT_PROJECT_FOLDER": "/opt/smartlect/run/uploads/",
    # assistant 仍单实例在 node1，但网关副本跑在三个节点上：base-url 必须指向 node1 的
    # 内网地址，否则副本节点上的网关会把 /api/assistant/** 转发到它本机不存在的 18000。
    "SMARTLECT_GROWTH_HOST": "0.0.0.0",
    "SMARTLECT_GROWTH_BASE_URL": f"http://{n1}:18000",
}
lines = [line for line in open(path).read().splitlines()
         if line and line.split("=", 1)[0] not in updates and line.split("=", 1)[0] != "SMARTLECT_APP_SERVICES"]
lines += [f"{k}={v}" for k, v in updates.items()]
open(path, "w").write("\n".join(lines) + "\n")
print("runtime.env updated with", len(updates), "cluster keys")
PY
chmod 600 "$RT"

log "6) starting apps against the cluster middleware..."
systemctl start smartlect-apps
sleep 15
cd "$ROOT" && /usr/bin/python3 scripts/runtime.py apps-check

log "CUTOVER COMPLETE — apps are up in single-node form against clustered middleware"
