-- 查询索引补齐（ADR-0018）：product_info 按分类（前台分类页 UNION 查询）
-- 与上下架状态过滤此前均无二级索引，只有主键 + 全文索引。
-- INPLACE + LOCK=NONE 在线创建；回滚可按需 DROP INDEX（见 docs/改动记录/2026-10-14）。

ALTER TABLE product_info
    ADD INDEX idx_product_category (category_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE product_info
    ADD INDEX idx_product_pcategory (p_category_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE product_info
    ADD INDEX idx_product_status (status),
    ALGORITHM=INPLACE, LOCK=NONE;
