-- 查询索引补齐（ADR-0018）：user_coupon 按 user_id（我的券列表）与 status
-- （临期未用扫描 selectExpiringUnused）此前均无二级索引，只有主键。
-- INPLACE + LOCK=NONE 在线创建；回滚可按需 DROP INDEX（见 docs/改动记录/2026-10-14）。

ALTER TABLE user_coupon
    ADD INDEX idx_uc_user_status (user_id, status),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE user_coupon
    ADD INDEX idx_uc_status (status),
    ALGORITHM=INPLACE, LOCK=NONE;
