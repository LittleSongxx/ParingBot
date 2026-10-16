#!/usr/bin/env bash
# 压测后的数据一致性对账（node1 执行，只读）
#
# 为什么必须做：本次改动动了三处与"一笔订单走完"直接相关的机制——
# 事务边界（RPC 移出事务）、MQ 投递方式（发布确认改异步）、幂等账本口径。
# 只数订单条数看不出问题，要把跨库的账实关系对上。
set -uo pipefail
q() { docker exec smartlect-mysql-1 bash -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot -N $1 -e \"$2\"" 2>/dev/null; }

echo "===== 压测数据对账 ====="
echo
echo "--- 订单侧 ---"
ORDER_TOTAL=$(q smartlect_order "SELECT COUNT(*) FROM order_info")
ITEM_TOTAL=$(q smartlect_order "SELECT COUNT(*) FROM order_item")
LOGISTICS_TOTAL=$(q smartlect_order "SELECT COUNT(*) FROM order_logistics_info")
PAID=$(q smartlect_order "SELECT COUNT(*) FROM order_info WHERE order_status=1")
ITEM_ORPHAN=$(q smartlect_order "SELECT COUNT(*) FROM order_item i LEFT JOIN order_info o ON i.order_id=o.order_id WHERE o.order_id IS NULL")
printf "  order_info        = %s\n" "$ORDER_TOTAL"
printf "  order_item        = %s（每单至少 1 条）\n" "$ITEM_TOTAL"
printf "  order_logistics   = %s\n" "$LOGISTICS_TOTAL"
printf "  已支付(order_status=1) = %s\n" "$PAID"
printf "  孤儿明细（无对应订单）= %s\n" "$ITEM_ORPHAN"

echo
echo "--- 幂等账本（下单请求与订单应一比一） ---"
q smartlect_order "SELECT CONCAT('  ', status, ' = ', COUNT(*)) FROM order_request_idempotency GROUP BY status"
echo

echo "--- 支付侧 ---"
PAY_TOTAL=$(q smartlect_pay "SELECT COUNT(*) FROM pay_trade_record")
PAY_SUCCESS=$(q smartlect_pay "SELECT COUNT(*) FROM pay_trade_record WHERE trade_status=1")
printf "  pay_trade_record  = %s\n" "$PAY_TOTAL"
printf "  支付成功(trade_status=1) = %s\n" "$PAY_SUCCESS"
q smartlect_pay "SELECT CONCAT('  trade_status=', trade_status, ' → ', COUNT(*)) FROM pay_trade_record GROUP BY trade_status"
echo

echo "--- 库存侧 ---"
CHANGES=$(q smartlect_stock "SELECT COUNT(*) FROM stock_change_record")
printf "  stock_change_record = %s（每单一次扣减）\n" "$CHANGES"

echo
echo "===== 一致性判定 ====="
ok=0; fail=0
check() { # $1=描述 $2=左值 $3=右值
  if [ "$2" = "$3" ]; then echo "  ✓ $1（$2）"; ok=$((ok+1))
  else echo "  ✗ $1：左=$2 右=$3"; fail=$((fail+1)); fi
}
check "下单请求数 == 订单数"           "$ORDER_TOTAL" "$(q smartlect_order "SELECT COUNT(*) FROM order_request_idempotency WHERE status='COMPLETED'")"
check "支付记录数 == 订单数"           "$ORDER_TOTAL" "$PAY_TOTAL"
check "已支付订单数 == 支付成功数"      "$PAID" "$PAY_SUCCESS"
check "库存扣减记录数 == 订单数"        "$ORDER_TOTAL" "$CHANGES"
if [ "$ITEM_TOTAL" -ge "$ORDER_TOTAL" ] 2>/dev/null; then echo "  ✓ 明细数 >= 订单数（$ITEM_TOTAL >= $ORDER_TOTAL）"; ok=$((ok+1)); else echo "  ✗ 明细数少于订单数"; fail=$((fail+1)); fi
if [ "$ITEM_ORPHAN" = "0" ]; then echo "  ✓ 无孤儿明细"; ok=$((ok+1)); else echo "  ✗ 存在孤儿明细 $ITEM_ORPHAN 条"; fail=$((fail+1)); fi
echo
echo "  通过 $ok 项，失败 $fail 项"
