from tortoise import fields
from tortoise.models import Model


class AgentRun(Model):
    """Agent 运行记录表，一次匹配发起对应一条记录。

    入参快照、最终结论、失败原因、耗时都在这里，运行失败之后能复现当时的输入。
    """

    id = fields.IntField(pk=True)
    # 运行编号，唯一索引 uk_agent_run_no
    run_no = fields.CharField(max_length=64, unique=True)
    # 所属匹配任务
    task_id = fields.IntField(null=True)
    # 触发这次运行的用户
    user_id = fields.IntField(null=True)
    # 匹配编排
    run_type = fields.CharField(max_length=100, null=True)
    # 运行中 / 已完成 / 运行失败
    run_status = fields.CharField(max_length=50, default="运行中")
    # 当前已调度轮次
    current_round = fields.IntField(default=0)
    # 实际用掉的调度轮次
    total_round = fields.IntField(default=0)
    input_snapshot = fields.TextField(null=True)
    # 收尾原因与最终结论
    output_summary = fields.TextField(null=True)
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "agent_run"


class AgentStep(Model):
    """Agent 步骤记录表，调度时间线的全部数据来源。

    主管每一次派单也落一条（step_type 为「调度」），否则时间线上看不到是谁决定的。
    """

    id = fields.IntField(pk=True)
    run_id = fields.IntField()
    # 第几轮调度
    round_no = fields.IntField(default=0)
    # 本轮内的第几步
    step_index = fields.IntField(default=0)
    # 这一步是哪个角色在做：SUPERVISOR / PORTRAIT / SCREENER / AUDITOR
    agent_code = fields.CharField(max_length=50, null=True)
    # 调度 / 工具调用 / 角色结论
    step_type = fields.CharField(max_length=20)
    step_name = fields.CharField(max_length=255, null=True)
    tool_code = fields.CharField(max_length=100, null=True)
    request_params = fields.TextField(null=True)
    response_result = fields.TextField(null=True)
    # 已完成 / 运行失败
    step_status = fields.CharField(max_length=20, default="已完成")
    error_message = fields.CharField(max_length=500, null=True)
    start_time = fields.DatetimeField(null=True)
    end_time = fields.DatetimeField(null=True)
    cost_millis = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "agent_step"


class ToolCallLog(Model):
    """工具调用日志表，成功失败都记，另外记返回行数。"""

    id = fields.IntField(pk=True)
    run_id = fields.IntField()
    # 发起这次调用的 Agent 角色编码
    agent_code = fields.CharField(max_length=50, null=True)
    tool_code = fields.CharField(max_length=100)
    request_params = fields.TextField(null=True)
    response_result = fields.TextField(null=True)
    row_count = fields.IntField(null=True)
    # 是 / 否
    success = fields.CharField(max_length=10, default="是")
    error_message = fields.CharField(max_length=500, null=True)
    cost_millis = fields.IntField(null=True)
    create_time = fields.DatetimeField(null=True)

    class Meta:
        table = "tool_call_log"
