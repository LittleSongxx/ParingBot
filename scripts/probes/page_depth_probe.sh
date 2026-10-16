#!/usr/bin/env bash
# 深分页与索引探针：在**独立临时库**里复现 order_info 的两种查询形态，量化两件事：
#   ① V5__query_indexes.sql 的 (user_id, order_time) 索引值多少（未建索引 vs 建后）
#   ② offset 深分页的残余代价（首页 vs 第 2000 页），为 PageUtils 的页码上限提供依据
#
# 为什么用临时库而不是直接在生产库上试：本地库的 Flyway 历史可能落后于迁移目录，
# 手工补索引会让下次启动时 Flyway 重复执行 V5 而失败（Duplicate key name）。
# 临时库同名结构、同样的数据形状，测完即删，不碰应用状态。
#
# 用法：bash scripts/probes/page_depth_probe.sh [行数，默认 50000]
# 输出：stdout（可重定向为证据文件）
set -euo pipefail

ROWS="${1:-50000}"
CONTAINER="${SMARTLECT_MYSQL_CONTAINER:-smartlect-mysql-1}"
DB="smartlect_perf_probe"

mysql_exec() {
  docker exec -i "$CONTAINER" sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysql -uroot -t -e "$0"' "$1"
}

echo "# 深分页与索引探针"
echo "# 容器 $CONTAINER · 临时库 $DB · 订单 ${ROWS} 行 · 明细 $((ROWS * 3 / 2)) 行"
echo

echo "## 0. 建临时库与同构表（结构取自 smartlect_order.order_info / order_item 的 DDL 形状）"
mysql_exec "
DROP DATABASE IF EXISTS $DB;
CREATE DATABASE $DB CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE TABLE $DB.order_info (
  order_id varchar(32) NOT NULL,
  amount decimal(10,2) DEFAULT NULL,
  user_id varchar(15) DEFAULT NULL,
  order_time datetime DEFAULT NULL,
  order_status tinyint(1) DEFAULT NULL,
  pay_channel varchar(10) DEFAULT NULL,
  pay_order_id varchar(32) DEFAULT NULL,
  subject varchar(200) DEFAULT NULL,
  PRIMARY KEY (order_id)
) ENGINE=InnoDB;
CREATE TABLE $DB.order_item (
  order_item_id varchar(32) NOT NULL,
  order_id varchar(32) DEFAULT NULL,
  product_id varchar(20) DEFAULT NULL,
  buy_count int DEFAULT NULL,
  PRIMARY KEY (order_item_id)
) ENGINE=InnoDB;
"

echo "## 1. 灌入合成数据（$ROWS 笔订单 / 1.5x 明细，用户均匀分布在 500 个 user_id 上）"
mysql_exec "
SET SESSION cte_max_recursion_depth = 1000000;
INSERT INTO $DB.order_info (order_id, amount, user_id, order_time, order_status, pay_channel, pay_order_id, subject)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < $ROWS)
SELECT CONCAT('20261', LPAD(n, 27, '0')),
       99.00 + (n % 900),
       CONCAT('88000', LPAD(n % 500, 5, '0')),
       FROM_UNIXTIME(1760000000 + n * 7),
       (n % 4),
       'mock',
       CONCAT('PO', LPAD(n, 28, '0')),
       CONCAT('probe subject ', n)
FROM seq;
INSERT INTO $DB.order_item (order_item_id, order_id, product_id, buy_count)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < $((ROWS * 3 / 2)))
SELECT CONCAT('IT', LPAD(n, 30, '0')),
       CONCAT('20261', LPAD(1 + (n % $ROWS), 27, '0')),
       LPAD(100000000000000 + (n % 47), 15, '0'),
       1
FROM seq;
ANALYZE TABLE $DB.order_info, $DB.order_item;
SELECT COUNT(*) AS orders FROM $DB.order_info;
"

# 两种真实形态：用户侧（按 user_id 过滤，索引后 offset 只扫该用户的少量行）与
# 管理端（按状态过滤、无用户约束——深分页的代价主要落在这里）
Q_USER="SELECT o.order_id, o.amount, i.order_item_id FROM $DB.order_info o LEFT JOIN $DB.order_item i ON o.order_id = i.order_id WHERE o.user_id = '8800000123' ORDER BY o.order_time DESC LIMIT 100, 20"
Q_ADMIN_FIRST="SELECT o.order_id, o.amount, i.order_item_id FROM $DB.order_info o LEFT JOIN $DB.order_item i ON o.order_id = i.order_id WHERE o.order_status IN (0,1) ORDER BY o.order_time DESC LIMIT 20"
Q_ADMIN_DEEP="SELECT o.order_id, o.amount, i.order_item_id FROM $DB.order_info o LEFT JOIN $DB.order_item i ON o.order_id = i.order_id WHERE o.order_status IN (0,1) ORDER BY o.order_time DESC LIMIT 40000, 20"

echo
echo "## 2. 未建二级索引（= 本地库当前状态，Flyway 尚未应用到 V5 的形状）"
for label in 用户第6页:Q_USER 管理端首页:Q_ADMIN_FIRST 管理端第2000页:Q_ADMIN_DEEP; do
  name="${label%:*}"; sql="${label##*:}"
  echo "--- EXPLAIN ANALYZE [$name]"
  mysql_exec "EXPLAIN ANALYZE ${!sql};" | sed 's/^/    /'
done

echo
echo "## 3. 加上 V5__query_indexes.sql 的索引后（(user_id, order_time) + 明细 order_id）"
mysql_exec "
ALTER TABLE $DB.order_info ADD INDEX idx_order_user_time (user_id, order_time), ALGORITHM=INPLACE, LOCK=NONE;
ALTER TABLE $DB.order_item ADD INDEX idx_item_order (order_id), ALGORITHM=INPLACE, LOCK=NONE;
ANALYZE TABLE $DB.order_info, $DB.order_item;
"
for label in 用户第6页:Q_USER 管理端首页:Q_ADMIN_FIRST 管理端第2000页:Q_ADMIN_DEEP; do
  name="${label%:*}"; sql="${label##*:}"
  echo "--- EXPLAIN ANALYZE [$name]"
  mysql_exec "EXPLAIN ANALYZE ${!sql};" | sed 's/^/    /'
done

echo
echo "## 4. 结论口径"
echo "- 对比第 2 节与第 3 节的 actual rows / actual time：索引把用户维度的排序分页从全表扫描"
echo "  + filesort 降到区间扫描；这是 V5 迁移的价值，也是\"本地库若落后于迁移\"的代价。"
echo "- 对比同一节内的管理端首页与第 2000 页：即使有索引，offset 仍要扫过前 offset 行，代价随页码"
echo "  线性增长——这就是 PageUtils 加页码上限护栏的依据（真正消除它需要 keyset/两阶段分页）。"
echo "- 临时库 $DB 保留供复跑比对；删除：DROP DATABASE $DB;"
