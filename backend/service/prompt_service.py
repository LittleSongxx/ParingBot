"""Prompt 模板业务逻辑。

发给模型的提示词全部存在这张表里，代码按编码取模板，所以这一页管的不是一段文字，
而是整条 AI 链路的输入。三条规则值得留意：

1. 编码是代码取模板的依据。已经被 Agent 角色用着的模板不允许改编码，也不允许删除，
   只能停用。删掉之后那个角色会在取模板那一步直接报错。
2. 变量清单从模板内容里自动识别，不让管理员手工维护，说明和内容就不会各说各话。
3. 预览会把变量填进去渲染一遍，看到的就是真正发给模型的那段文本。
   停用的模板也允许预览：一般是先改好内容、看一遍拼出来对不对，再决定启用。
"""

import re

from tortoise.expressions import Q

from ai import prompt_loader
from common.exception_handler import CustomException
from common.pagination import normalize_page
from common.result import PageInfo
from common.times import format_datetime
from models import AgentDefinition, PromptTemplate

# 页面上的场景下拉由这里给出，页面不自己维护一份
SCENES = ("Agent调度", "Agent画像", "Agent筛选", "Agent审核")
# 编码是代码里的检索键，统一用大写字母、数字和下划线的写法，例如 PORTRAIT_PROMPT
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,49}$")
YES_NO_OPTIONS = ("是", "否")
MAX_NAME_LENGTH = 255
MAX_REMARK_LENGTH = 500
MAX_CONTENT_LENGTH = 20000
# 预览时单个变量最多填多少字，防止把一大段原文贴进预览框
PREVIEW_VALUE_MAX_LENGTH = 2000


def template_dict(template: PromptTemplate, used_by: list[str] | None = None) -> dict:
    return {
        "id": template.id,
        "code": template.code,
        "name": template.name,
        "scene": template.scene,
        "variables": template.variables,
        # 预览弹窗按这个清单生成输入框，页面不用自己去解析 variables 那串文本
        "variable_names": prompt_loader.list_variables(template.content),
        "content": template.content,
        "enabled": template.enabled,
        "remark": template.remark,
        # 哪些 Agent 角色正用着这条模板，页面上要显示出来，也用它拦删除
        "used_by": used_by or [],
        "update_time": format_datetime(template.update_time),
    }


def scene_options() -> list[str]:
    return list(SCENES)


async def _used_by(code: str | None) -> list[str]:
    """哪些 Agent 角色正把这条模板当提示词用。"""
    if not code:
        return []
    agents = await AgentDefinition.filter(prompt_code=code)
    return [agent.agent_name for agent in agents]


async def _reference_map() -> dict[str, list[str]]:
    """一次取全：模板编码到正在用它的角色名称。列表页少查几次库。"""
    mapping: dict[str, list[str]] = {}
    for agent in await AgentDefinition.all():
        if agent.prompt_code:
            mapping.setdefault(agent.prompt_code, []).append(agent.agent_name)
    return mapping


async def _get(template_id: int | None) -> PromptTemplate:
    template = await PromptTemplate.get_or_none(id=template_id)
    if template is None:
        raise CustomException("未找到这条 Prompt 模板，请刷新列表后重试")
    return template


def _check_name(raw) -> str:
    name = str(raw or "").strip()
    if not name:
        raise CustomException("请填写模板名称")
    if len(name) > MAX_NAME_LENGTH:
        raise CustomException(f"模板名称最多 {MAX_NAME_LENGTH} 个字符")
    return name


async def _check_code(raw, template_id: int | None) -> str:
    code = str(raw or "").strip()
    if not code:
        raise CustomException("请填写模板编码")
    if not CODE_PATTERN.match(code):
        raise CustomException(
            "模板编码请用大写字母、数字和下划线，以字母开头，长度 3 到 50 位，"
            "例如 PORTRAIT_PROMPT")
    duplicate = PromptTemplate.filter(code=code)
    if template_id is not None:
        duplicate = duplicate.exclude(id=template_id)
    if await duplicate.exists():
        raise CustomException(f"已经有编码为 {code} 的模板了，编码是代码取模板的依据，不能重复")
    return code


def _check_scene(raw) -> str | None:
    scene = str(raw or "").strip()
    if not scene:
        return None
    if scene not in SCENES:
        raise CustomException(f"使用场景请从这几项里选：{'、'.join(SCENES)}")
    return scene


def _check_remark(raw) -> str | None:
    remark = str(raw or "").strip()
    if len(remark) > MAX_REMARK_LENGTH:
        raise CustomException(f"备注最多 {MAX_REMARK_LENGTH} 个字符")
    return remark or None


def _check_enabled(raw) -> str:
    enabled = str(raw or "").strip()
    if enabled not in YES_NO_OPTIONS:
        raise CustomException("启用状态只能是是或否")
    return enabled


def _check_content(raw) -> str:
    content = str(raw or "")
    if not content.strip():
        raise CustomException("请填写模板内容")
    if len(content) > MAX_CONTENT_LENGTH:
        raise CustomException(f"模板内容最多 {MAX_CONTENT_LENGTH} 个字符")
    return content


def _check_variables(content: str) -> str:
    """从模板内容里识别变量并拼成存库的样子。

    变量清单要放进 variables 列，列长 500，太多说明这个模板该拆成两个：
    一次要填十几个变量的模板，管理员自己也不敢改。
    """
    variables = prompt_loader.extract_variables(content)
    if len(variables) > prompt_loader.VARIABLES_MAX_LENGTH:
        raise CustomException(
            f"模板里的变量太多了，变量清单超过 {prompt_loader.VARIABLES_MAX_LENGTH} 个字符，"
            f"请把这个模板拆成两个")
    return variables


async def select_page(keyword: str = "", scene: str = "", enabled: str = "",
                      page_num: int = 1, page_size: int = 10) -> PageInfo:
    """管理端的模板分页查询。

    关键词同时匹编码和名称：管理员记得住名字还是编码不一定，
    只按一个查会让他先自己确认到底记住的是哪个。
    """
    page_num, page_size = normalize_page(page_num, page_size)
    query = PromptTemplate.all()
    if keyword:
        query = query.filter(Q(code__contains=keyword) | Q(name__contains=keyword))
    if scene:
        query = query.filter(scene=scene)
    if enabled:
        query = query.filter(enabled=enabled)
    templates = await query.order_by("id").offset(
        (page_num - 1) * page_size).limit(page_size)
    total = await query.count()
    references = await _reference_map()
    return PageInfo(total=total, list=[
        template_dict(item, references.get(item.code, [])) for item in templates])


async def add(payload: dict) -> None:
    code = await _check_code(payload.get("code"), None)
    content = _check_content(payload.get("content"))
    await PromptTemplate.create(
        code=code,
        name=_check_name(payload.get("name")),
        scene=_check_scene(payload.get("scene")),
        content=content,
        # 变量清单跟着内容走，内容和说明就不会各说各话
        variables=_check_variables(content),
        enabled=_check_enabled(payload.get("enabled")),
        remark=_check_remark(payload.get("remark")),
    )


async def update(template_id: int | None, payload: dict) -> None:
    template = await _get(template_id)
    content = _check_content(payload.get("content"))
    code = await _check_code(payload.get("code"), template.id)
    used_by = await _used_by(template.code)
    # 角色按编码取提示词，改了编码角色就取不到它，跑到那一步才报错的话很难往回找
    if used_by and code != template.code:
        raise CustomException(
            f"这条模板正被「{'、'.join(used_by)}」使用，编码不能改："
            f"改了编码这些地方就取不到提示词了。要换编码请先新建一条模板，"
            f"再把用它的地方换过去")
    await PromptTemplate.filter(id=template.id).update(
        code=code,
        name=_check_name(payload.get("name")),
        scene=_check_scene(payload.get("scene")),
        content=content,
        variables=_check_variables(content),
        enabled=_check_enabled(payload.get("enabled")),
        remark=_check_remark(payload.get("remark")),
    )


async def update_enabled(template_id: int, enabled: str) -> None:
    """停用或启用一条模板。

    停用是给管理层留的后退手段：模板内容改坏了先停掉，链路会明确报错说它被停用了，
    而不是继续用一份错的内容。
    """
    template = await _get(template_id)
    await PromptTemplate.filter(id=template.id).update(enabled=_check_enabled(enabled))


async def remove(template_id: int) -> None:
    template = await _get(template_id)
    used_by = await _used_by(template.code)
    if used_by:
        raise CustomException(
            f"「{template.name}」正被「{'、'.join(used_by)}」使用，"
            f"删掉之后这些地方会取不到提示词。如果只是想让它暂时不生效，"
            f"请改成停用；确实要删除，请先把它从用它的地方换掉")
    await PromptTemplate.filter(id=template.id).delete()


async def preview(template_id: int, values: dict) -> str:
    """把变量值填进模板，返回真正会发给模型的那段完整文本。"""
    template = await _get(template_id)
    if not template.content or not template.content.strip():
        raise CustomException(f"「{template.name}」的内容还是空的，请先补充内容")
    text_values = {}
    for key, value in (values or {}).items():
        text = "" if value is None else str(value)
        if len(text) > PREVIEW_VALUE_MAX_LENGTH:
            raise CustomException(
                f"变量 {key} 填的内容太长了，预览最多填 {PREVIEW_VALUE_MAX_LENGTH} 个字符")
        text_values[str(key)] = text
    return prompt_loader.fill(template.content, text_values)
