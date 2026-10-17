-- MQ 补偿审查日志（coupon 库）。
--
-- 背景：全额退款要把已核销的券还回去，这条动作走 MQ（refund-coupon-return）。
-- 消费连续失败后 MqConsumeFailureRecorder 需要把失败落库；此前 coupon 库没有这张表，
-- 写入直接抛异常被吞掉，只留一行日志——券会永久不回。表结构与 order/stock/user/product/admin 一致。
--
-- 重放范围：coupon 的消费失败是幂等动作（USED→NOUSE 条件更新），由
-- mq.compensation.auto-replay-consume=true 打开自动重放；其它域保持默认关闭、交给人工。
CREATE TABLE IF NOT EXISTS mq_compensation_log
(
    log_id            int auto_increment                  NOT NULL COMMENT '日志ID' PRIMARY KEY,
    idempotency_key   varchar(128)                        NOT NULL COMMENT '幂等键',
    exchange          varchar(64)                         NOT NULL COMMENT '交换机',
    routing_key       varchar(64)                         NOT NULL COMMENT '路由键',
    biz_scene         varchar(32)                         NULL     COMMENT '业务场景',
    payload_json      mediumtext                          NULL     COMMENT '消息体 JSON',
    reliability_level varchar(16) DEFAULT 'HIGH'          NOT NULL COMMENT '发送级别',
    error_message     varchar(512)                        NULL     COMMENT '失败原因',
    retry_count       int         DEFAULT 0               NOT NULL COMMENT '重放次数',
    status            int         DEFAULT 0               NOT NULL COMMENT '0待处理 1处理中 2已重放成功 3重放失败 4已忽略',
    create_time       datetime                            NOT NULL COMMENT '创建时间',
    update_time       datetime                            NULL     COMMENT '更新时间',
    handle_time       datetime                            NULL     COMMENT '运维处理时间',
    handle_remark     varchar(512)                        NULL     COMMENT '处理备注',
    CONSTRAINT uk_idempotency_key UNIQUE (idempotency_key),
    KEY idx_mq_compensation_status (status),
    KEY idx_mq_compensation_scene (biz_scene),
    KEY idx_mq_compensation_create (create_time)
) COMMENT 'MQ补偿审查日志（coupon库）' CHARSET = utf8mb4;
