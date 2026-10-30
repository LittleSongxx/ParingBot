"""Prompt 模板接口测试。

覆盖模板列表、编码规则、变量自动识别、预览渲染、模板被 Agent 角色引用时的拦截，
以及取模板那三项校验的失败路径。

预览用例专门盯住一件事：模板里的 JSON 示例带花括号，填变量时不能被当成占位符，
否则真实模板一用就报 KeyError。
"""

import pytest

from ai import prompt_loader
from common.exception_handler import CustomException
from models import PromptTemplate

TEST_MARK = "单元测试专用"
# 初始化数据里的模板
SEED_CODES = ("SUPERVISOR_PROMPT", "PORTRAIT_PROMPT", "SCREENER_PROMPT", "AUDITOR_PROMPT")
# 四套模板各配在一个 Agent 角色上
SEED_REFERENCES = {
    "SUPERVISOR_PROMPT": "合租管家",
    "PORTRAIT_PROMPT": "画像师",
    "SCREENER_PROMPT": "筛选官",
    "AUDITOR_PROMPT": "审核官",
}


def _list_templates(client, admin_headers, **params) -> list:
    body = client.get("/promptTemplate/selectPage", params={"page_size": 100, **params},
                      headers=admin_headers).json()
    assert body["code"] == "200"
    return body["data"]["list"]


def _row_of(client, admin_headers, code) -> dict:
    for row in _list_templates(client, admin_headers, keyword=code):
        if row["code"] == code:
            return row
    raise AssertionError(f"列表里没找到编码为 {code} 的模板")


def _add(client, admin_headers, code, **fields) -> dict:
    payload = {
        "code": code,
        "name": f"测试模板{TEST_MARK}",
        "scene": "Agent画像",
        "content": "请回答：{question}",
        "enabled": "否",
    }
    payload.update(fields)
    return client.post("/promptTemplate/add", json=payload, headers=admin_headers).json()


def _cleanup(client, admin_headers) -> None:
    """把测试造出来的模板删干净。"""
    for row in _list_templates(client, admin_headers, keyword=TEST_MARK):
        if TEST_MARK in (row["name"] or ""):
            client.delete(f"/promptTemplate/delete/{row['id']}", headers=admin_headers)


def test_seed_templates_cover_four_codes(client, admin_headers):
    """初始化数据里四个场景各有一套模板，变量清单和内容说的是同一件事。"""
    rows = {row["code"]: row for row in _list_templates(client, admin_headers)}
    for code in SEED_CODES:
        assert code in rows, f"初始化数据里缺少 {code}，请确认已执行 paringbot.sql"
        assert rows[code]["enabled"] == "是"
    for row in rows.values():
        expected = " ".join("{" + name + "}" for name in row["variable_names"])
        assert row["variables"] == expected, f"{row['code']} 的变量清单和模板内容对不上"


def test_seed_templates_show_which_module_uses_them(client, admin_headers):
    """每套模板都标出正拿它当提示词的 Agent 角色。"""
    rows = {row["code"]: row for row in _list_templates(client, admin_headers)}
    for code, user_name in SEED_REFERENCES.items():
        assert rows[code]["used_by"] == [user_name]


def test_scene_options(client, admin_headers):
    """场景下拉由后端给出，页面不自己维护一份。"""
    body = client.get("/promptTemplate/sceneOptions", headers=admin_headers).json()
    assert body["code"] == "200"
    assert body["data"] == ["Agent调度", "Agent画像", "Agent筛选", "Agent审核"]


def test_variables_are_recognised_from_content(client, admin_headers):
    """变量清单从内容里自动识别，JSON 示例里的花括号不算变量。"""
    _cleanup(client, admin_headers)
    code = "TEST_JSON_PROMPT_UNIT"
    content = '请根据 {question} 和 {context} 回答。\n只输出 JSON：\n{"answer": "答案", "score": 0}'
    assert _add(client, admin_headers, code, content=content)["code"] == "200"
    row = _row_of(client, admin_headers, code)
    assert row["variable_names"] == ["question", "context"]
    assert row["variables"] == "{question} {context}"
    _cleanup(client, admin_headers)


def test_extract_variables_keeps_order_and_dedupes():
    """同一个变量出现两次只留一次，顺序按第一次出现的位置。"""
    content = "先 {b} 再 {a} 又 {b}"
    assert prompt_loader.list_variables(content) == ["b", "a"]
    assert prompt_loader.extract_variables(content) == "{b} {a}"
    assert prompt_loader.list_variables(None) == []


def test_code_rule_is_enforced(client, admin_headers):
    """编码是代码取模板的键，统一大写字母加下划线的写法。"""
    body = _add(client, admin_headers, "lower_case_code")
    assert body["code"] == "500"
    assert "大写字母" in body["msg"]
    assert _add(client, admin_headers, "AB")["code"] == "500"


def test_duplicate_code_is_rejected(client, admin_headers):
    """编码全表唯一，重复的编码会让代码取到哪一条变得不确定。"""
    body = _add(client, admin_headers, "PORTRAIT_PROMPT")
    assert body["code"] == "500"
    assert "不能重复" in body["msg"]


def test_empty_content_is_rejected(client, admin_headers):
    """内容为空拼不出 Prompt，保存时就拦住。"""
    body = _add(client, admin_headers, "TEST_EMPTY_PROMPT_UNIT", content="   ")
    assert body["code"] == "500"
    assert "模板内容" in body["msg"]


def test_unknown_scene_is_rejected(client, admin_headers):
    """场景从固定几项里选，乱填之后按场景筛选就查不到它。"""
    body = _add(client, admin_headers, "TEST_SCENE_PROMPT_UNIT", scene="随便写的场景")
    assert body["code"] == "500"
    assert "使用场景请从这几项里选" in body["msg"]


def test_referenced_template_cannot_be_deleted(client, admin_headers):
    """被 Agent 角色用着的模板删不掉，接口要给出替代做法。"""
    row = _row_of(client, admin_headers, "PORTRAIT_PROMPT")
    body = client.delete(f"/promptTemplate/delete/{row['id']}", headers=admin_headers).json()
    assert body["code"] == "500"
    assert "画像师" in body["msg"]
    assert "停用" in body["msg"]
    # 拦下来之后模板还在
    assert _row_of(client, admin_headers, "PORTRAIT_PROMPT")["enabled"] == "是"


def test_referenced_template_code_cannot_change(client, admin_headers):
    """被角色用着的模板不能改编码，角色是按编码取提示词的。"""
    row = _row_of(client, admin_headers, "PORTRAIT_PROMPT")
    body = client.put("/promptTemplate/update", json={
        "id": row["id"],
        "code": "PORTRAIT_PROMPT_NEW",
        "name": row["name"],
        "scene": row["scene"],
        "content": row["content"],
        "enabled": row["enabled"],
        "remark": row["remark"],
    }, headers=admin_headers).json()
    assert body["code"] == "500"
    assert "编码不能改" in body["msg"]
    assert _row_of(client, admin_headers, "PORTRAIT_PROMPT")["id"] == row["id"]


def test_update_recomputes_variables(client, admin_headers):
    """内容改了变量清单跟着重算，不会留下和内容对不上的旧清单。"""
    _cleanup(client, admin_headers)
    code = "TEST_RECOMPUTE_UNIT"
    assert _add(client, admin_headers, code, content="你好 {name}")["code"] == "200"
    row = _row_of(client, admin_headers, code)
    assert row["variables"] == "{name}"
    body = client.put("/promptTemplate/update", json={
        "id": row["id"],
        "code": code,
        "name": row["name"],
        "scene": row["scene"],
        "content": "你好 {name}，你也在 {city} 吗",
        "enabled": row["enabled"],
    }, headers=admin_headers).json()
    assert body["code"] == "200"
    assert _row_of(client, admin_headers, code)["variables"] == "{name} {city}"
    _cleanup(client, admin_headers)


def test_too_many_variables_is_rejected(client, admin_headers):
    """变量清单超出列长时拦住，提示把模板拆开。"""
    content = " ".join("{" + "v%03d" % index + "}" for index in range(100))
    body = _add(client, admin_headers, "TEST_MANY_VARS_UNIT", content=content)
    assert body["code"] == "500"
    assert "变量太多" in body["msg"]


def test_preview_keeps_json_braces(client, admin_headers):
    """预览把变量填进去，模板里的 JSON 示例原样保留。"""
    _cleanup(client, admin_headers)
    code = "TEST_PREVIEW_PROMPT_UNIT"
    content = '给 {who} 写一句开场白。\n只输出 JSON：\n{"content": "话术"}'
    assert _add(client, admin_headers, code, content=content)["code"] == "200"
    row = _row_of(client, admin_headers, code)
    body = client.post("/promptTemplate/preview",
                       json={"id": row["id"], "values": {"who": "小明"}},
                       headers=admin_headers).json()
    assert body["code"] == "200"
    assert "小明" in body["data"]
    assert '{"content": "话术"}' in body["data"]
    assert "{who}" not in body["data"]
    _cleanup(client, admin_headers)


def test_preview_reports_missing_variable(client, admin_headers):
    """有变量没填值时拦住，别把占位符原样发给模型。"""
    _cleanup(client, admin_headers)
    code = "TEST_PREVIEW_MISSING_UNIT"
    assert _add(client, admin_headers, code, content="请根据 {question} 回答")["code"] == "200"
    row = _row_of(client, admin_headers, code)
    body = client.post("/promptTemplate/preview", json={"id": row["id"], "values": {}},
                       headers=admin_headers).json()
    assert body["code"] == "500"
    assert "还没有填值" in body["msg"]
    assert "question" in body["msg"]
    _cleanup(client, admin_headers)


def test_disabled_template_still_previews(client, admin_headers):
    """停用的模板也允许预览：先看拼出来的内容对不对，再决定启用。"""
    _cleanup(client, admin_headers)
    code = "TEST_DISABLED_PREVIEW_UNIT"
    assert _add(client, admin_headers, code, content="你好 {name}")["code"] == "200"
    row = _row_of(client, admin_headers, code)
    assert row["enabled"] == "否"
    body = client.post("/promptTemplate/preview",
                       json={"id": row["id"], "values": {"name": "小红"}},
                       headers=admin_headers).json()
    assert body["code"] == "200"
    assert "小红" in body["data"]
    _cleanup(client, admin_headers)


def test_member_cannot_manage_templates(client, user_headers):
    """提示词是平台级配置，租客账号看不到也改不了。"""
    body = client.get("/promptTemplate/selectPage", headers=user_headers).json()
    assert body["code"] == "403"


async def test_load_missing_code(db):
    """编码不存在时报错要说清去哪个页面添加。"""
    with pytest.raises(CustomException) as error:
        await prompt_loader.load("NO_SUCH_TEMPLATE_UNIT")
    assert "没有找到编码为" in error.value.message


async def test_disabled_template_cannot_be_loaded(db):
    """停用的模板取不到，报错要说清去启用它，而不是悄悄用一份旧内容。"""
    template = await PromptTemplate.create(
        code="TEST_LOAD_DISABLED_UNIT", name=f"停用模板{TEST_MARK}",
        content="请根据 {question} 回答", enabled="否")
    try:
        with pytest.raises(CustomException) as error:
            await prompt_loader.load("TEST_LOAD_DISABLED_UNIT")
        assert "已被停用" in error.value.message
    finally:
        await PromptTemplate.filter(id=template.id).delete()


async def test_empty_content_cannot_be_rendered(db):
    """内容为空时取模板就该拦住，不用等到模型那边报错。"""
    template = await PromptTemplate.create(
        code="TEST_LOAD_EMPTY_UNIT", name=f"空内容模板{TEST_MARK}",
        content="   ", enabled="是")
    try:
        with pytest.raises(CustomException) as error:
            await prompt_loader.render("TEST_LOAD_EMPTY_UNIT")
        assert "内容是空的" in error.value.message
    finally:
        await PromptTemplate.filter(id=template.id).delete()



async def test_seed_prompts_are_readable_utf8(db):
    """四套种子提示词必须是可读中文且带运行时契约关键字。

    历史教训：02 号种子 SQL 少了 SET NAMES，导入后审核官提示词变成
    UTF-8→latin1 双重编码乱码，真实模型读到的是乱码而 FakeModel 测试毫无察觉。
    """
    rows = await PromptTemplate.filter(code__in=SEED_CODES)
    assert len(rows) == len(SEED_CODES)
    contract = {
        "SUPERVISOR_PROMPT": "next_agent",
        "PORTRAIT_PROMPT": "evidence",
        "SCREENER_PROMPT": "candidates",
        "AUDITOR_PROMPT": "audited",
    }
    for row in rows:
        content = row.content or ""
        chinese = [ch for ch in content if "\u4e00" <= ch <= "\u9fff"]
        assert len(chinese) >= 50, (row.code, len(chinese))
        assert contract[row.code] in content, row.code
        assert "Ã" not in content and "ä½" not in content, row.code
        assert "【安全约束】" in content, row.code
