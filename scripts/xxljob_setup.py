#!/usr/bin/env python3
"""注册 xxl-job 执行器组与任务定义（幂等，可反复执行）。

批次三把九个 @Scheduled 任务迁成 @XxlJob handler（现役共十个，含后续新增的幂等对账上报），但 handler 只是"可被调用的
入口"——任务本身（执行器组、cron、启用状态）存在 xxl-job 的库里，必须在调度
中心登记才会被触发。只加注解不登记的结果是任务静默停摆：没有报错、没有日志，
出问题时只表现为"业务该自动发生的事一直没发生"。

用法：
  python3 scripts/xxljob_setup.py            # 注册全部执行器组与任务
  python3 scripts/xxljob_setup.py --dry-run  # 只打印将要执行的 SQL

幂等语义：执行器组按 app_name、任务按 (执行器组, handler) 判重，已存在即跳过，
不覆盖控制台上的人工调整（cron / 启停状态）。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / 'run' / 'runtime.env'
DB = 'smartlect_xxljob'

# 需要登记执行器组的服务：XxlJobConfig 在 common 里无条件装配，九个服务都会起
# XxlJobSpringExecutor 并按 appname 自动注册到调度中心；但调度中心侧的执行器组
# 记录不会自动创建，缺了它注册会一直失败。这里九个都要登记。
EXECUTORS = ['smartlect-admin', 'smartlect-cart', 'smartlect-coupon', 'smartlect-gateway',
             'smartlect-order', 'smartlect-pay', 'smartlect-product', 'smartlect-stock',
             'smartlect-user']

# (执行器组, handler, cron, 说明)；cron 为 Quartz 六段式，按原 @Scheduled 周期折算。
# 绑定的服务必须是该 handler Bean 真正注册的那个：
#   - common 模块的 handler（outboxDispatch / mqCompensationReplay）在多个服务里都
#     有 Bean，绑到 order（MQ 主链）即可，FIRST 路由保证只有一个实例执行；
#   - userTempBanReconcile 只在 user 注册，且受 app.common-scheduling.enabled 控制。
JOBS = [
    ('smartlect-order', 'payOrderPoll', '*/5 * * * * ?', '支付单轮询（原 fixedDelay 5s）'),
    ('smartlect-order', 'outboxDispatch', '*/5 * * * * ?', 'Outbox 兜底投递（原 fixedDelay 5s）'),
    ('smartlect-order', 'refundSagaReconcile', '*/30 * * * * ?', '退款 Saga 对账（原 fixedDelay 30s）'),
    ('smartlect-order', 'mqCompensationReplay', '0 * * * * ?', 'MQ 补偿重放（原 fixedDelay 60s）'),
    ('smartlect-order', 'orderAutoReceiptReconcile', '0 */10 * * * ?', '订单自动确认收货对账（原 fixedDelay 600s）'),
    ('smartlect-order', 'orderIdempotencyReconcile', '0 */5 * * * ?', '幂等账本待核对上报（每 5 分钟）'),
    ('smartlect-admin', 'autoDataTask', '0 0 1 * * ?', '管理端统计快照（原 cron 0 0 1）'),
    ('smartlect-user', 'userTempBanReconcile', '0 * * * * ?', '临时封禁到期解封（原 fixedDelay 60s）'),
    ('smartlect-user', 'imageModerationCleanup', '0 15 * * * ?', '图片审核残留清理（原 cron 0 15 *）'),
    ('smartlect-coupon', 'couponRushReconcile', '0 */10 * * * ?', '秒杀库存对账（原 cron 0 */10）'),
]


def load_env():
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def mysql(sql, capture=False):
    """经 MySQL 容器执行 SQL；走容器内的 root 口令文件，不落明文到命令行。"""
    command = ['docker', 'compose', '--project-name', 'smartlect', '--env-file', str(ENV_FILE),
               '-f', str(ROOT / 'deploy/compose.yaml'),
               'exec', '-T', 'mysql', 'sh', '-ec',
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "$1"', 'xxljob-setup', sql]
    return subprocess.run(command, cwd=ROOT, check=True, text=True,
                          capture_output=capture).stdout


def executor_sql(app_name):
    return (f"INSERT INTO {DB}.xxl_job_group(app_name, title, address_type, update_time) "
            f"SELECT '{app_name}', '{app_name.replace('smartlect-', '')}', 0, NOW() "
            f"WHERE NOT EXISTS (SELECT 1 FROM {DB}.xxl_job_group WHERE app_name = '{app_name}');")


def job_sql(app_name, handler, cron, desc):
    return (f"INSERT INTO {DB}.xxl_job_info(job_group, job_desc, add_time, update_time, author, "
            f"alarm_email, schedule_type, schedule_conf, misfire_strategy, executor_route_strategy, "
            f"executor_handler, executor_param, executor_block_strategy, executor_timeout, "
            f"executor_fail_retry_count, glue_type, glue_source, glue_remark, glue_updatetime, "
            f"child_jobid, trigger_status, trigger_last_time, trigger_next_time) "
            f"SELECT g.id, '{desc}', NOW(), NOW(), 'smartlect', '', 'CRON', '{cron}', 'DO_NOTHING', "
            f"'FIRST', '{handler}', '', 'SERIAL_EXECUTION', 0, 0, 'BEAN', '', 'smartlect 自动登记', "
            f"NOW(), '', 1, 0, 0 FROM {DB}.xxl_job_group g "
            f"WHERE g.app_name = '{app_name}' AND NOT EXISTS ("
            f"SELECT 1 FROM {DB}.xxl_job_info i WHERE i.job_group = g.id AND i.executor_handler = '{handler}');")


def main():
    dry_run = '--dry-run' in sys.argv
    load_env()
    if dry_run:
        for name in EXECUTORS:
            print(executor_sql(name))
        for job in JOBS:
            print(job_sql(*job))
        return 0

    mysql(';'.join(executor_sql(name) for name in EXECUTORS) + ';')
    print(f'执行器组已登记：{len(EXECUTORS)} 个')
    mysql(';'.join(job_sql(*job) for job in JOBS) + ';')
    print(f'任务已登记：{len(JOBS)} 个')

    rows = mysql(f"SELECT g.app_name, i.executor_handler, i.schedule_conf, i.trigger_status "
                 f"FROM {DB}.xxl_job_info i JOIN {DB}.xxl_job_group g ON g.id = i.job_group "
                 f"ORDER BY i.id;", capture=True)
    print('当前调度中心任务：')
    for row in rows.splitlines():
        app, handler, cron, status = row.split('\t')
        print(f'  {"启用" if status == "1" else "停止"}  {app:<18} {handler:<28} {cron}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
