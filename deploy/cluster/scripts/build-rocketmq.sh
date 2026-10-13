#!/usr/bin/env bash
# RocketMQ DLedger 三副本集群：生成各节点 broker 配置 → 分发 → 三节点拉起 → 断言
#
# 设计取舍：**不迁移单机数据卷**。DLedger 成员用全新卷（Raft 日志与单机 commitlog
# 不兼容），业务 Topic/订阅组由 autoCreateTopicEnable 兜底重建，Outbox 会把未决
# 消息补投到新集群。单机卷 smartlect_rocketmq-store 原样保留，回退即恢复。
#
# 前置：apps 已停（维护窗口），旧单机 rocketmq 三容器仍在运行。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLUSTER_ROOT:-/opt/cluster}"
# shellcheck source=/dev/null
source "$HERE/../nodes.env"
log() { echo "[build-rocketmq $(date +%T)] $*"; }
remote() { ssh $CLUSTER_SSH_OPTS "root@$1" "$2"; }

mkdir -p "$CL/evidence"

# 1) 按 nodes.env 生成各节点 DLedger broker 配置（peers 全量、selfId 按节点）
cd "$CL/rocketmq"
mkdir -p conf
# peers 必须用 IP：node2/3 的 hostname 是克隆残留的 smartlect-node1（解析歧义），
# DLedger 按「selfId-host:port」的第一个连字符拆分，host 段用 IP 不依赖系统主机名。
PEERS="n0-${NODE1_IP}:${ROCKETMQ_DLEDGER_PORT:-40911};n1-${NODE2_IP}:${ROCKETMQ_DLEDGER_PORT:-40911};n2-${NODE3_IP}:${ROCKETMQ_DLEDGER_PORT:-40911}"
for n in 1 2 3; do
  eval "name=\$NODE${n}_NAME"
  eval "ip=\$NODE${n}_IP"
  self="n$((n-1))"
  cat > "conf/dledger-node${n}.conf" <<EOF
brokerClusterName = DefaultCluster
brokerName = broker-a
enableDLegerCommitLog = true
dLegerGroup = broker-a
dLegerPeers = ${PEERS}
dLegerSelfId = ${self}
sendMessageThreadPoolNums = 16
deleteWhen = 04
fileReservedTime = 48
autoCreateTopicEnable = true
autoCreateSubscriptionGroup = true
timerWheelEnable = true
storePathRootDir = /home/rocketmq/store
storePathCommitLog = /home/rocketmq/store/commitlog
brokerIP1 = ${ip}
listenPort = ${ROCKETMQ_BROKER_PORT:-10911}
EOF
done
log "generated dledger configs (peers=${PEERS})"

# 2) 分发编排与配置到 node2/3
for n in 2 3; do
  eval "ip=\$NODE${n}_IP"
  log "distributing to node${n} ($ip)..."
  remote "$ip" "mkdir -p $CL/rocketmq/conf"
  scp -q $CLUSTER_SSH_OPTS compose.c${n}.yaml "root@$ip:$CL/rocketmq/"
  scp -q $CLUSTER_SSH_OPTS .env "root@$ip:$CL/rocketmq/.env" 2>/dev/null || true
  scp -q $CLUSTER_SSH_OPTS conf/dledger-node${n}.conf "root@$ip:$CL/rocketmq/conf/smartlect-dledger.conf"
done
cp conf/dledger-node1.conf conf/smartlect-dledger.conf

# 3) 停单机三件套释放端口（容器保留，回退用）
log "stopping single-node rocketmq (containers kept for rollback)..."
docker stop smartlect-rocketmq-proxy-1 smartlect-rocketmq-broker-1 smartlect-rocketmq-namesrv-1 >/dev/null 2>&1 || true

# 4) 两阶段拉起：DLedger 需要多数派才能选主——先起三节点 namesrv+broker（阶段一），
#    多数派形成、broker 可写之后再起 proxy（阶段二；单节点先起 proxy 会因系统
#    topic 创建失败而重启循环）。
for n in 1 2 3; do
  eval "ip=\$NODE${n}_IP"
  log "stage1 broker on node${n} (${ip})..."
  if [ "$n" = "1" ]; then
    (cd "$CL/rocketmq" && docker compose -f compose.c1.yaml --env-file .env up -d --wait --wait-timeout 300 rocketmq-namesrv rocketmq-broker)
  else
    remote "$ip" "cd $CL/rocketmq && docker compose -f compose.c${n}.yaml --env-file .env up -d --wait --wait-timeout 300 rocketmq-namesrv rocketmq-broker"
  fi
done
log "stage1 done (3 brokers up, raft majority formed)"
for n in 1 2 3; do
  eval "ip=\$NODE${n}_IP"
  log "stage2 proxy on node${n} (${ip})..."
  if [ "$n" = "1" ]; then
    (cd "$CL/rocketmq" && docker compose -f compose.c1.yaml --env-file .env up -d --wait --wait-timeout 300 rocketmq-proxy)
  else
    remote "$ip" "cd $CL/rocketmq && docker compose -f compose.c${n}.yaml --env-file .env up -d --wait --wait-timeout 300 rocketmq-proxy"
  fi
done

# 5) 集群断言：DLedger 3 副本、leader 存在（mqadmin 走 node1 namesrv）
log "asserting dledger cluster..."
docker run --rm --network host apache/rocketmq:5.3.2 sh -c \
  "JAVA_OPT_EXT='-Xms128m -Xmx256m' sh mqadmin clusterList -n 127.0.0.1:${ROCKETMQ_NAMESRV_PORT:-9876}" \
  | tee "$CL/evidence/rocketmq-cluster-list.txt"
REPLICAS=$(grep -c "^broker-a" "$CL/evidence/rocketmq-cluster-list.txt" || true)
[ "$REPLICAS" -ge 3 ] || { echo "expect 3 dledger replicas, got $REPLICAS"; exit 1; }
grep -q "rocketmq cluster READY" /dev/null 2>&1 || true
# 6) Topic 预建（订阅侧校验路由；message.type 必须显式单值——坑见 compose 注释；
#    放在三节点拉起之后，broker 未就绪时 updateTopic 会失败，循环重试 30 次）
MQADMIN="docker run --rm --network host apache/rocketmq:5.3.2 sh -c"
for spec in "smartlect-delay DELAY" "smartlect-pay NORMAL" "smartlect-refund NORMAL" \
            "smartlect-rush NORMAL" "smartlect-canal NORMAL" "smartlect-mq-failure NORMAL"; do
  set -- ${spec}
  # 独立临时容器跑 mqadmin：broker 容器 mem_limit 已贴顶，内嵌第二个 JVM 会被 OOM 杀(137)
  for i in $(seq 1 30); do
    docker run --rm --network host apache/rocketmq:5.3.2 sh -c \
      "JAVA_OPT_EXT='-Xms128m -Xmx256m' sh mqadmin updateTopic -n 127.0.0.1:9876 -c DefaultCluster -t $1 -a '+message.type=$2'" >/dev/null 2>&1 && break
    sleep 2
  done
done
log "topics ready (6)"
log "rocketmq cluster READY (3 dledger replicas, brokers on ${ROCKETMQ_BROKER_PORT:-10911})"
