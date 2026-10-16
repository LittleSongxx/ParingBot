-- 订单行冗余下单幂等键（2026-10-16 审计 M8 的闭环第一步）。
-- 背景：幂等账本只存 userId + commandType + 幂等键，不存业务 id，因此
-- INCONCLUSIVE / 陈旧 PROCESSING 只能靠人工带参数核对。把下单命令的幂等键写到订单行上，
-- 对账就能反查"这个键到底有没有成交"。
-- 语义：只对 POST_ORDER / POST_ORDER_V2 写入；历史行为 NULL（迁移不做回填——
-- 回填需要账本与订单的时间窗匹配，属独立的一次性脚本，见改动记录）。
-- 成本：MySQL 8 加可空列是 INSTANT 操作，不阻塞读写；索引用于按键反查。
ALTER TABLE order_info
    ADD COLUMN idempotency_key varchar(64) NULL COMMENT '下单命令幂等键（对账反查用）';

CREATE INDEX idx_order_idem_key ON order_info (idempotency_key);
