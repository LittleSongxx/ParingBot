#!/usr/bin/env bash
# 压测后的数据一致性对账（node1 执行，只读）。
#
# 旧版把“订单数”“支付单数”“库存变更记录数”都按 1:1 比较，忽略了：
#   - 一笔下单命令可以生成多个子单（多商品）；
#   - 同一 payOrderId 只对应一笔支付/一次 ORDER_DEDUCT；
#   - 库存账本还包含 ORDER_CLOSE_RESTORE / REFUND_RESTORE；
#   - 幂等账本还包含退款/取消命令。
# 这里按业务键的真实粒度比较，默认只看最近 2 小时，避免历史行干扰。
set -uo pipefail
SINCE="${1:-$(date -d '2 hours ago' '+%Y-%m-%d %H:%M:%S')}"
UNTIL="${2:-$(date '+%Y-%m-%d %H:%M:%S')}"

q() {
  local db="$1" sql="$2"
  docker exec smartlect-mysql-1 bash -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N "$0" -e "$1"' "$db" "$sql" 2>/dev/null
}

ORDERS=$(q smartlect_order "SELECT COUNT(*) FROM order_info WHERE order_time >= '$SINCE' AND order_time < '$UNTIL'")
PAY_IDS=$(q smartlect_order "SELECT COUNT(DISTINCT pay_order_id) FROM order_info WHERE order_time >= '$SINCE' AND order_time < '$UNTIL' AND order_status IN (1,2,3,6,7)")
PAY_TRADES=$(q smartlect_pay "SELECT COUNT(*) FROM pay_trade_record WHERE create_time >= '$SINCE' AND create_time < '$UNTIL' AND trade_status IN (1,3)")
POST_KEYS=$(q smartlect_order "SELECT COUNT(DISTINCT idempotency_key) FROM order_info WHERE order_time >= '$SINCE' AND order_time < '$UNTIL' AND order_status <> 0 AND idempotency_key IS NOT NULL")
POST_CMDS=$(q smartlect_order "SELECT COUNT(*) FROM order_request_idempotency WHERE create_time >= '$SINCE' AND create_time < '$UNTIL' AND status='COMPLETED' AND command_type='POST_ORDER'")
PAID_WITHOUT_COMMAND=$(q smartlect_order "SELECT COUNT(*) FROM order_info o LEFT JOIN order_request_idempotency i ON o.idempotency_key COLLATE utf8mb4_general_ci=i.idempotency_key COLLATE utf8mb4_general_ci AND i.command_type='POST_ORDER' WHERE o.order_time >= '$SINCE' AND o.order_time < '$UNTIL' AND o.order_status IN (1,2,3,6,7) AND (i.idempotency_key IS NULL OR i.status <> 'COMPLETED')")
DEDUCTS=$(q smartlect_stock "SELECT COUNT(*) FROM stock_change_record WHERE created_at >= '$SINCE' AND created_at < '$UNTIL' AND change_type='ORDER_DEDUCT'")
PAID_IDS=$(q smartlect_order "SELECT COUNT(DISTINCT pay_order_id) FROM order_info WHERE order_time >= '$SINCE' AND order_time < '$UNTIL' AND order_status <> 0 AND order_status IN (1,2,3,7)")
SETTLED=$(q smartlect_pay "SELECT COUNT(*) FROM pay_trade_record WHERE create_time >= '$SINCE' AND create_time < '$UNTIL' AND trade_status IN (1,3)")
ORDERS_WITHOUT_PAY=$(q smartlect_order "SELECT COUNT(*) FROM order_info o LEFT JOIN smartlect_pay.pay_trade_record p ON o.pay_order_id COLLATE utf8mb4_general_ci=p.pay_order_id COLLATE utf8mb4_general_ci WHERE o.order_time >= '$SINCE' AND o.order_time < '$UNTIL' AND o.order_status IN (1,2,3,6,7) AND p.pay_order_id IS NULL")
ORDERS_WITHOUT_DEDUCT=$(q smartlect_order "SELECT COUNT(*) FROM order_info o WHERE o.order_time >= '$SINCE' AND o.order_time < '$UNTIL' AND o.order_status IN (1,2,3,6,7) AND NOT EXISTS (SELECT 1 FROM smartlect_stock.stock_change_record s WHERE s.business_key COLLATE utf8mb4_general_ci=CONCAT('order-deduct:',o.pay_order_id) COLLATE utf8mb4_general_ci)")
ITEM_TOTAL=$(q smartlect_order "SELECT COUNT(*) FROM order_item i JOIN order_info o ON i.order_id=o.order_id WHERE o.order_time >= '$SINCE' AND o.order_time < '$UNTIL' AND o.order_status <> 0")
ITEM_ORPHAN=$(q smartlect_order "SELECT COUNT(*) FROM order_item i LEFT JOIN order_info o ON i.order_id=o.order_id WHERE o.order_id IS NULL")

echo "===== 压测数据对账（$SINCE ~ $UNTIL） ====="
printf '  orders=%s  distinct_pay_ids=%s  pay_trades=%s\n' "$ORDERS" "$PAY_IDS" "$PAY_TRADES"
printf '  post_keys=%s  post_completed=%s  order_deducts=%s\n' "$POST_KEYS" "$POST_CMDS" "$DEDUCTS"
printf '  paid_pay_ids=%s  settled_trades=%s\n' "$PAID_IDS" "$SETTLED"
printf '  orders_without_pay=%s  orders_without_deduct=%s  items=%s  item_orphans=%s\n' \
  "$ORDERS_WITHOUT_PAY" "$ORDERS_WITHOUT_DEDUCT" "$ITEM_TOTAL" "$ITEM_ORPHAN"

ok=0; fail=0
check_eq() {
  local label="$1" left="$2" right="$3"
  if [ "$left" = "$right" ]; then echo "  ✓ $label（$left）"; ok=$((ok+1));
  else echo "  ✗ $label：左=$left 右=$right"; fail=$((fail+1)); fi
}
check_zero() { check_eq "$1" "$2" "0"; }

check_eq "支付单数 == 支付流水数" "$PAY_IDS" "$PAY_TRADES"
check_zero "已付款订单都有 COMPLETED POST_ORDER 幂等记录" "$PAID_WITHOUT_COMMAND"
if [ "$DEDUCTS" -ge "$PAY_IDS" ] 2>/dev/null; then echo "  ✓ ORDER_DEDUCT 数 >= 已付款支付单数（$DEDUCTS >= $PAY_IDS）"; ok=$((ok+1)); else echo "  ✗ ORDER_DEDUCT 少于已付款支付单数（$DEDUCTS < $PAY_IDS）"; fail=$((fail+1)); fi
check_eq "已支付/已发货/已完成/部分退款支付单数 == 已结算流水数" "$PAID_IDS" "$SETTLED"
check_zero "没有订单缺支付流水" "$ORDERS_WITHOUT_PAY"
check_zero "没有订单缺 ORDER_DEDUCT" "$ORDERS_WITHOUT_DEDUCT"
check_zero "没有孤儿订单明细" "$ITEM_ORPHAN"
if [ "$ITEM_TOTAL" -ge "$ORDERS" ] 2>/dev/null; then echo "  ✓ 明细数 >= 订单数（$ITEM_TOTAL >= $ORDERS）"; ok=$((ok+1));
else echo "  ✗ 明细数少于订单数（$ITEM_TOTAL < $ORDERS）"; fail=$((fail+1)); fi

echo "  通过 $ok 项，失败 $fail 项"
[ "$fail" -eq 0 ]
