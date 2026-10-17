-- 订单状态变更历史：状态机 CAS 成功后同事务写入，用于审计与“幽灵跳变”排查。
-- 只追加，不更新；from_status 为 NULL 表示创建。
create table if not exists order_status_log
(
    log_id        bigint auto_increment primary key,
    order_id      varchar(40) not null,
    pay_order_id  varchar(40) null,
    from_status   tinyint     null,
    to_status     tinyint     not null,
    event         varchar(32) not null,
    operator_type varchar(16) null,
    operator_id   varchar(40) null,
    request_id    varchar(64) null,
    remark        varchar(200) null,
    create_time   datetime(3) not null default current_timestamp(3),
    key idx_status_log_order (order_id, create_time),
    key idx_status_log_pay (pay_order_id, create_time)
);
