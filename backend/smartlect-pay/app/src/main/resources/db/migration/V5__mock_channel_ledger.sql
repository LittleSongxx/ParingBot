-- Mock 渠道流水账：与支付意图/退款表分开记录“渠道侧确认过的事实”，用于日对账。
-- event_id 由业务键派生（complete:<payOrderId> / refund:<refundOrderId>），重复写入被唯一键吸收。
create table if not exists pay_mock_channel_ledger
(
    ledger_id      bigint auto_increment primary key,
    event_id       varchar(96)   not null comment '幂等事件键',
    event_type     varchar(16)   not null comment 'COMPLETE / REFUND',
    pay_order_id   varchar(32)   not null comment '支付意图号',
    refund_order_id varchar(64)  null comment '退款单号（REFUND 事件）',
    amount         decimal(10, 2) not null comment '事件金额',
    status         varchar(16)   not null comment '渠道事件结果',
    created_at     datetime(3)   not null default current_timestamp(3),
    unique key uk_mock_ledger_event (event_id),
    key idx_mock_ledger_pay (pay_order_id, created_at)
) comment 'Mock 渠道事件流水（只追加）' collate = utf8mb4_general_ci;

-- 上线前已完成的模拟支付/退款补一份流水，否则首次日对账会把历史数据全部报成差异。
insert ignore into pay_mock_channel_ledger
    (event_id, event_type, pay_order_id, refund_order_id, amount, status, created_at)
select concat('complete:', pay_order_id), 'COMPLETE', pay_order_id, null, pay_amount, 'SUCCESS',
       coalesce(pay_time, create_time, current_timestamp(3))
from pay_trade_record
where pay_channel = 'mock'
  and trade_status in (1, 3);

insert ignore into pay_mock_channel_ledger
    (event_id, event_type, pay_order_id, refund_order_id, amount, status, created_at)
select concat('refund:', refund_order_id), 'REFUND', source_pay_order_id, refund_order_id, refund_amount, 'SUCCESS',
       confirmed_at
from pay_mock_refund;
