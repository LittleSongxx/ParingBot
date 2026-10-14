-- 查询索引补齐（ADR-0018）。
-- 背景：order_info / order_item 等核心查询表此前只有主键——按 user_id 查订单、
-- 轮询待付款单、按 order_id join 明细全部走全表扫；测试临时表都建了索引而生产迁移没有。
-- 说明：MySQL 8 二级索引用 INPLACE + LOCK=NONE 在线创建，不阻塞读写；
-- 线上大表执行仍建议低峰进行（见 docs/改动记录/2026-10-14 启用说明）。
-- 回滚：索引用于加速、不承载约束，可按需 DROP INDEX（见改动记录回滚说明）。

ALTER TABLE order_info
    ADD INDEX idx_order_user_time (user_id, order_time),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE order_info
    ADD INDEX idx_order_status_time (order_status, order_time),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE order_info
    ADD INDEX idx_order_pay_order (pay_order_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE order_item
    ADD INDEX idx_item_order (order_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE order_coupon_rel
    ADD INDEX idx_rel_user_coupon (user_coupon_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE order_logistics_info_record
    ADD INDEX idx_record_order (order_id),
    ALGORITHM=INPLACE, LOCK=NONE;
