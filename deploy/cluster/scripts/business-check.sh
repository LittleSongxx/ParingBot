#!/usr/bin/env bash
# 压测期间/之后的业务侧对账（node1 执行，只读）
#
# 用途：确认发压制造的是"真实成交"而不是"200 但没落账"，并为改动记录提供证据。
set -euo pipefail
q() { docker exec smartlect-mysql-1 bash -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot -N $1 -e \"$2\"" 2>/dev/null; }

echo "=== 订单 ==="
q smartlect_order "SELECT CONCAT('order_info 行数=', COUNT(*)) FROM order_info"
# 状态语义：0 待付款 / 1 已付款 / 2 已发货 / 3 已完成（见 OrderStatusEnum）
q smartlect_order "SELECT CONCAT('  待付款=', SUM(order_status=0), ' 已付款=', SUM(order_status=1), ' 已发货=', SUM(order_status=2)) FROM order_info"
q smartlect_order "SELECT CONCAT('  order_item 行数=', COUNT(*)) FROM order_item"
echo "=== 支付 ==="
q smartlect_pay "SELECT CONCAT('pay_trade_record 行数=', COUNT(*)) FROM pay_trade_record"
q smartlect_pay "SELECT CONCAT('  成功=', COUNT(*)) FROM pay_trade_record WHERE status=2"
echo "=== 购物车 ==="
q smartlect_cart "SELECT CONCAT('product_cart 行数=', COUNT(*)) FROM product_cart"
echo "=== 库存（demo 前缀） ==="
q smartlect_stock "SELECT CONCAT('sku_stock 总库存=', SUM(stock)) FROM sku_stock"
echo "=== MQ 堆积 ==="
docker exec rocketmq-broker sh mqadmin consumerProgress -n 127.0.0.1:9876 -g G_smartlect_pay_success 2>/dev/null | tail -2 | head -1 || echo "  消费组查询不可用"'
