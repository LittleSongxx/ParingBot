#!/usr/bin/env bash
# 按服务归属 CPU（修正版：按 PID 差分，PID 在窗口内稳定）
#
# 上一版按进程名 join 导致笛卡尔积、数值荒谬。这里用 PID 作键，窗口内 PID 不会变。
set -uo pipefail
WINDOW="${1:-5}"
HZ=$(getconf CLK_TCK)

sweep() {
  for pid in /proc/[0-9]*; do
    [ -r "$pid/stat" ] || continue
    cmd=$(tr '\0' ' ' < "$pid/cmdline" 2>/dev/null) || continue
    # 只关心本工程相关进程
    case "$cmd" in
      *run/apps/*) svc=$(echo "$cmd" | grep -oE 'run/apps/[a-z-]+' | cut -d/ -f3) ;;
      *nacos*)     svc="nacos" ;;
      *redis*)     svc="redis" ;;
      *) continue ;;
    esac
    read -r ut st < <(awk '{print $14, $15}' "$pid/stat" 2>/dev/null)
    echo "${pid##*/} $svc $((ut + st))"
  done
}

sweep > /tmp/svc-before.txt
sleep "$WINDOW"
sweep > /tmp/svc-after.txt

join -j 1 <(sort -n /tmp/svc-before.txt) <(sort -n /tmp/svc-after.txt) 2>/dev/null \
  | awk -v hz="$HZ" -v w="$WINDOW" '{p = 100.0 * ($5 - $3) / hz / w; if (p > 1) printf "%s %.1f\n", $4, p}' \
  | sort -k2 -rn | awk '{printf "  %-14s %6.1f%%\n", $1, $2}'
echo "  （窗口 ${WINDOW}s；100% = 占满一个核；本机 $(nproc) 核）"
