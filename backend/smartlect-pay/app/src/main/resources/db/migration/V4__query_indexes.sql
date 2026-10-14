-- 查询索引补齐（ADR-0018）：trade_status 驱动对账扫描（xxl-job 轮询待对账单）、
-- user_id + create_time 驱动用户支付单列表，此前均无二级索引。
-- INPLACE + LOCK=NONE 在线创建；回滚可按需 DROP INDEX（见 docs/改动记录/2026-10-14）。

ALTER TABLE pay_trade_record
    ADD INDEX idx_trade_status_time (trade_status, create_time),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE pay_trade_record
    ADD INDEX idx_trade_user_time (user_id, create_time),
    ALGORITHM=INPLACE, LOCK=NONE;
