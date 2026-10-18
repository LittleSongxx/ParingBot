from tortoise import fields
from tortoise.models import Model


class AiModelConfig(Model):
    """AI 模型配置表。

    全项目的大模型都按这张表的配置构建，改 Key、换模型不用重启服务。
    model_purpose 说明这条配置给哪一个 Agent 角色用，每个用途同一时间只启用一条。
    """

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, null=True)
    provider = fields.CharField(max_length=100, null=True)
    base_url = fields.CharField(max_length=500, null=True)
    api_key = fields.CharField(max_length=500, null=True)
    model_name = fields.CharField(max_length=255, null=True)
    # 温度，空则用服务端默认
    temperature = fields.DecimalField(max_digits=4, decimal_places=2, null=True)
    # 最大输出 Token，空则用服务端默认
    max_tokens = fields.IntField(null=True)
    # 调度 / 画像 / 筛选 / 审核
    model_purpose = fields.CharField(max_length=50, null=True)
    enabled = fields.CharField(max_length=10, default="是")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "ai_model_config"


class PromptTemplate(Model):
    """Prompt 模板表。

    发给模型的提示词全部存在这里，业务代码按 code 取模板，
    取的时候做「存在 / 启用 / 内容非空」三项校验，不用兜底的硬编码提示词。
    """

    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255, null=True)
    # 模板编码，业务代码按它取模板，唯一索引 uk_prompt_template_code
    code = fields.CharField(max_length=100, unique=True, null=True)
    scene = fields.CharField(max_length=100, null=True)
    # 模板里用 {变量名} 占位，填值时只替换这里声明过的变量
    variables = fields.CharField(max_length=500, null=True)
    content = fields.TextField(null=True)
    enabled = fields.CharField(max_length=10, default="是")
    remark = fields.CharField(max_length=500, null=True)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "prompt_template"


class SysConfig(Model):
    """系统参数表。

    Agent 的轮数上限、工具调用上限、放宽次数上限、交付人数这些闸门全部读这里，
    管理员在页面上改完立刻生效，改代码不用重启。
    """

    id = fields.IntField(pk=True)
    # 参数编码，唯一索引 uk_sys_config_key
    config_key = fields.CharField(max_length=100, unique=True)
    config_name = fields.CharField(max_length=255)
    config_value = fields.CharField(max_length=500, null=True)
    # 整数 / 文本 / 小数
    value_type = fields.CharField(max_length=20, default="整数")
    remark = fields.CharField(max_length=500, null=True)
    enabled = fields.CharField(max_length=10, default="是")
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sys_config"


class AgentDefinition(Model):
    """子 Agent 定义表。

    一个 Agent 角色在库里就是一行记录，本质是 role_prompt + tool_group 的组合。
    四个角色跑的是同一套执行引擎，换的只是这两样东西。
    enabled 是真开关：停用某个角色之后主管派不了它。
    """

    id = fields.IntField(pk=True)
    # SUPERVISOR / PORTRAIT / SCREENER / AUDITOR，唯一索引 uk_agent_definition_code
    agent_code = fields.CharField(max_length=50, unique=True)
    agent_name = fields.CharField(max_length=100)
    # 指向 prompt_template.code
    prompt_code = fields.CharField(max_length=100, null=True)
    # 画像 / 筛选 / 审核，主管不调工具所以为空
    tool_group = fields.CharField(max_length=50, null=True)
    # 该角色单次执行的工具调用上限，为空时取系统参数里的统一上限
    max_tool_call = fields.IntField(null=True)
    enabled = fields.CharField(max_length=10, default="是")
    sort = fields.IntField(default=0)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "agent_definition"


class FunctionTool(Model):
    """工具注册表。

    子 Agent 能用哪些工具由这张表决定，不是由代码里写了几个函数决定。
    tool_code 必须和工具实现里的函数名一致，enabled 是真开关。
    """

    id = fields.IntField(pk=True)
    # 唯一索引 uk_function_tool_code
    tool_code = fields.CharField(max_length=100, unique=True)
    tool_name = fields.CharField(max_length=255)
    # 这段描述会原样发给模型，要写清什么时候该调、什么时候不该调、参数取值范围
    description = fields.CharField(max_length=1000, null=True)
    # 参数的 JSON Schema 文本
    input_schema = fields.TextField(null=True)
    # 画像 / 筛选 / 审核，按它把工具分给不同的子 Agent
    tool_group = fields.CharField(max_length=50, null=True)
    # 一次调用最多返回多少行，防止把上下文撑爆
    max_return_rows = fields.IntField(null=True)
    enabled = fields.CharField(max_length=10, default="是")
    sort = fields.IntField(default=0)
    create_time = fields.DatetimeField(auto_now_add=True)
    update_time = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "function_tool"
