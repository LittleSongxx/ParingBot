-- RocketMQ 迁移（ADR-0016）：延迟消息改为任意精度定时投递。
-- 存绝对到期时间（epoch 毫秒）而非时长：Outbox 定时重试补发时按 now 折算剩余延迟，多次重试后自动收敛为立即投递。
ALTER TABLE local_message_outbox
    ADD COLUMN delivery_expire_at BIGINT NULL COMMENT '定时投递到期 epoch 毫秒，NULL 表示立即';
