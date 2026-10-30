from tortoise import fields
from tortoise.models import Model


class AiAssistLog(Model):
    """AI 辅助能力调用日志表（Phase 0）。

    资料教练、匹配解读官这类辅助能力每调用一次模型落一条。生产代码只把
    「摘要」写进来：提示词全文和输入载荷分别算 sha256，原文一律不落库，
    避免把租客自我介绍、联系方式等 PII 复制到日志表里。

    表结构见 deploy/mysql/init/05-ai-assist-log.sql；本表不建物理外键，
    member_id / prompt_code 都是逻辑关联。
    """

    id = fields.IntField(pk=True)
    # profile_coach / match_brief 等场景编码，和 helper 的 scene 参数一致
    scene = fields.CharField(max_length=32)
    # 关联租客（辅助能力场景可能不针对具体租客，允许为空）
    member_id = fields.IntField(null=True)
    # 用的哪条提示词模板（prompt_template.code）
    prompt_code = fields.CharField(max_length=64, null=True)
    # 提示词全文的 sha256，只用来比对「是不是同一份提示词」
    prompt_hash = fields.CharField(max_length=64, null=True)
    model_name = fields.CharField(max_length=128, null=True)
    # 输入载荷规范化 JSON 的 sha256，原始内容不落库
    input_digest = fields.CharField(max_length=64, null=True)
    latency_ms = fields.IntField(null=True)
    prompt_tokens = fields.IntField(null=True)
    completion_tokens = fields.IntField(null=True)
    # 成功 / 失败，失败原因另记在 error_message
    status = fields.CharField(max_length=16, default="成功")
    # 这次结果是否被用户采纳（0 否 / 1 是），给后续效果评估用
    adopted = fields.BooleanField(default=False)
    error_message = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "ai_assist_log"