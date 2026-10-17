-- Seata 退役后的残物清理（2026-10-16 审计）。
-- 背景：ADR-0001 移除 Seata 已多时，但 8 个业务库里仍留着它的 undo_log 表；它是历史
-- 遗留（无任何读取方），留着会让"是否还在用分布式事务框架"的审计口径含糊。
-- 幂等：全部 DROP TABLE IF EXISTS，可反复执行。
-- 用法（本地）：docker exec -i smartlect-mysql-1 sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysql -uroot' < scripts/cleanup_seata_leftovers.sql
-- 生产：低峰执行；执行前后各跑一次 ./scripts/dev.sh infra-check 确认应用未受影响。
DROP TABLE IF EXISTS smartlect_user.undo_log;
DROP TABLE IF EXISTS smartlect_product.undo_log;
DROP TABLE IF EXISTS smartlect_stock.undo_log;
DROP TABLE IF EXISTS smartlect_cart.undo_log;
DROP TABLE IF EXISTS smartlect_order.undo_log;
DROP TABLE IF EXISTS smartlect_pay.undo_log;
DROP TABLE IF EXISTS smartlect_coupon.undo_log;
DROP TABLE IF EXISTS smartlect_admin.undo_log;
