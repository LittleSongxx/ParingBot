from tortoise import fields
from tortoise.models import Model


class MatchTask(Model):
    """匹配任务表，租客点一次【发起匹配】产生一条任务。"""

    id = fields.IntField(pk=True)
    # 发起匹配的租客
    member_id = fields.IntField()
    # 任务编号，唯一索引 uk_match_task_no
    task_no = fields.CharField(max_length=64, unique=True)
    # 要求交付的人数
    deliver_count = fields.IntField(default=8)
    # 待执行 / 执行中 / 已完成 / 执行失败
    status = fields.CharField(max_length=20, default="待执行")
    # 实际调度轮数
    total_round = fields.IntField(default=0)
    # 实际交付人数
    delivered_count = fields.IntField(default=0)
    # 本次任务对应的运行记录
    run_id = fields.IntField(null=True)
    error_message = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "match_task"


class MatchCandidate(Model):
    """候选池表，筛选官筛出来的候选和审核官的结论都落在这一张表上。

    同一个候选只占一行，审核结论是同行的回填，不另起一张表。
    """

    id = fields.IntField(pk=True)
    task_id = fields.IntField()
    # 被筛出来的候选室友
    candidate_member_id = fields.IntField()
    # 第几轮筛出来的
    found_round = fields.IntField(default=1)
    # 筛选官给的初筛得分
    screen_score = fields.IntField(null=True)
    # 本轮放宽了什么，例如「预算上限 +200」，没放宽为空
    relax_note = fields.CharField(max_length=255, null=True)
    # 待审核 / 通过 / 否决
    audit_status = fields.CharField(max_length=20, default="待审核")
    # MISMATCH_HARD / PREFERENCE_CONFLICT / PORTRAIT_INSUFFICIENT
    reject_code = fields.CharField(max_length=30, null=True)
    reject_reason = fields.CharField(max_length=500, null=True)
    # 第几轮审的
    audit_round = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "match_candidate"


class MemberPortrait(Model):
    """租客画像表。

    补画像会产生新版本，旧版本保留，用于对比补画像前后审核通过率的变化。
    """

    id = fields.IntField(pk=True)
    member_id = fields.IntField()
    # 画像版本，从 1 开始累加
    version = fields.IntField(default=1)
    # 三类标签都是逗号分隔，取值来自词表与模型提炼
    personality_tags = fields.CharField(max_length=500, null=True)
    lifestyle_tags = fields.CharField(max_length=500, null=True)
    cohabit_need_tags = fields.CharField(max_length=500, null=True)
    # 一段话概括这位租客
    summary = fields.TextField(null=True)
    # 每个标签依据哪段原文，存 JSON 文本
    evidence = fields.TextField(null=True)
    # 本次补画像被要求重点补哪个维度
    focus_hint = fields.CharField(max_length=255, null=True)
    # 由哪次运行产出
    run_id = fields.IntField(null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "member_portrait"
