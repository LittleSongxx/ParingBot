#!/bin/bash
# Canal 启动前置：镜像无 envsubst，conf 目录挂载只读且单文件挂载点无法覆盖。
# 方案：模板挂到独立只读路径，注入环境变量后写入容器自身可写的 conf/。
set -e
TPL=/smartlect-canal-template.properties
DST=/home/admin/canal-server/conf/canal.properties
cp "$TPL" /tmp/canal.properties
for key in CANAL_ROCKETMQ_NAMESRV CANAL_MYSQL_ADDRESS CANAL_MYSQL_USER CANAL_MYSQL_PASSWORD; do
  value=$(printenv "$key")
  sed -i "s/\${$key}/$value/g" /tmp/canal.properties
done
cat /tmp/canal.properties > "$DST"
# 实例模板同样注入后写入 example/（目录可写）
cp /smartlect-canal-instance-template.properties /tmp/instance.properties
for key in CANAL_MYSQL_ADDRESS CANAL_MYSQL_USER CANAL_MYSQL_PASSWORD; do
  value=$(printenv "$key")
  sed -i "s/\${$key}/$value/g" /tmp/instance.properties
done
cat /tmp/instance.properties > /home/admin/canal-server/conf/example/instance.properties

# 等 namesrv 端口可达（compose depends_on 只保证 namesrv 进程健康检查通过，
# canal 的 producer 启动早一拍会因路由信息不全反复重试，这里最多等 30 秒）。
namesrv="${CANAL_ROCKETMQ_NAMESRV:-rocketmq-namesrv:9876}"
host="${namesrv%%:*}"
port="${namesrv##*:}"
for i in $(seq 1 30); do
  if (echo > /dev/tcp/"$host"/"$port") 2>/dev/null; then
    break
  fi
  sleep 1
done

# Topic 由 broker autoCreateTopicEnable 兜底创建，无需预声明（RabbitMQ 时代的
# 交换机预声明鸡蛋顺序问题在 RocketMQ 下不存在）。

exec /home/admin/app.sh
