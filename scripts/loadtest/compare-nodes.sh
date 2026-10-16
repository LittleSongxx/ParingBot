#!/usr/bin/env bash
# node2 / node3 差异采集（在每台机器本地执行，输出可直接 diff）
#
# 采集顺序刻意从"现象"往"原因"走：先看负载与 CPU 的矛盾，再看 D 态线程（负载高而 CPU 低的
# 唯一来源），再逐进程、逐容器、最后到内核与配置。两边输出同样格式，diff 一眼看出差异。
set -uo pipefail
echo "########## $(hostname) ##########"

echo "--- 基本 ---"
echo "内核: $(uname -r)  核数: $(nproc)  启动: $(uptime -s | tr ' ' '_')"
echo "负载: $(cut -d' ' -f1-3 /proc/loadavg)"
awk '/^cpu /{t=$2+$3+$4+$5+$6+$7+$8; i=$5; printf "开机以来: user=%.0f%% sys=%.0f%% idle=%.0f%% iowait=%.0f%% steal=%.0f%%\n", 100*$2/t, 100*$4/t, 100*$5/t, 100*$6/t, 100*$9/t}' /proc/stat
free -m | awk '/Mem:/{printf "内存: 总 %dM 可用 %dM\n", $2, $7}'
df -h / | awk 'NR==2{printf "磁盘: %s 已用 %s\n", $2, $5}'

echo "--- 线程状态分布（D 态是负载高而 CPU 低的唯一来源）---"
d=0; r=0; s=0; total=0
for st in /proc/[0-9]*/task/*/stat; do
  [ -r "$st" ] || continue
  total=$((total+1))
  case "$(awk '{print $3}' "$st" 2>/dev/null)" in
    D) d=$((d+1));; R) r=$((r+1));; S) s=$((s+1));;
  esac
done
echo "线程总数 $total：R(running)=$r  D(uninterruptible)=$d  S(sleeping)=$s"

echo "--- 各服务的线程数 ---"
for pid in $(pgrep -f 'run/apps' 2>/dev/null); do
  svc=$(tr '\0' ' ' < "/proc/$pid/cmdline" | grep -oE 'run/apps/[a-z-]+' | cut -d/ -f3)
  n=$(ls /proc/$pid/task 2>/dev/null | wc -l)
  dcount=0
  for t in /proc/$pid/task/*/stat; do
    [ -r "$t" ] || continue
    [ "$(awk '{print $3}' "$t" 2>/dev/null)" = "D" ] && dcount=$((dcount+1))
  done
  printf "  %-10s 线程 %-5s D态 %s\n" "$svc" "$n" "$dcount"
done

echo "--- 容器 ---"
for c in rabbit nacos redis sentinel; do
  cid=$(docker ps --format '{{.Names}}' | grep -m1 "$c" || true)
  [ -z "$cid" ] && continue
  echo "  $(docker stats --no-stream --format "{{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}}" "$cid" 2>/dev/null)"
  tn=$(docker exec "$cid" sh -c 'ls /proc/1/task 2>/dev/null | wc -l' 2>/dev/null || echo "?")
  echo "    $c 线程数(PID1): $tn"
done

echo "--- 连接数（按目标端口） ---"
ss -tn state established 2>/dev/null | awk '{print $4}' | grep -oE ':[0-9]+$' | sort | uniq -c | sort -rn | head -6

echo "--- 本机应用配置（非密钥项） ---"
grep -E '^SMARTLECT_(APP_SERVICES|APP_BIND_ADDRESS|APP_REGISTER_IP|JAVA_PROCESSORS|JAVA_XMX|DB_POOL_MAX_SIZE|REDIS_HOST|REDIS_PORT|MYSQL_HOST|NACOS_ADDR|PROJECT_FOLDER)' /opt/smartlect/run/runtime.env 2>/dev/null | sort

echo "--- 系统里跑着的其它东西 ---"
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print "  " $1}' | grep -vE "systemd|ssh|cron|dbus|network|agent|polkit|rsyslog|udev|getty|multipath|irqbalance|unattended|snapd|chrony|aliyun|cloud|aegis|docker|containerd|Modem|tuned|udisks|user@|nginx" | head -10
echo "  cron:"; ls /etc/cron.d/ 2>/dev/null | head -5
