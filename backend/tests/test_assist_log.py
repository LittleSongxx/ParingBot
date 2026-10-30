"""ai_assist_log 表 ORM 与 common.assist_log helper 的测试。

重点验证「只落摘要、不落原文」：提示词与输入分别算 sha256，PII 原文不会出现在
这条日志的任何列里；token 用量两种字段命名都能映射；失败原因截断到列宽；
写库失败不向主流程抛异常。

注：本表是 Phase 0 新增（05-ai-assist-log.sql），conftest 的 session 清扫夹具还没
包含它，所以这里用用例级夹具按 scene 里的测试标记回收。当前运行库需要由 Lead
统一 rebuild（或手工导入 05 SQL）后这些用例才能跑通。
"""

import pytest

from common.assist_log import (
    ERROR_LIMIT,
    HASH_LENGTH,
    log_assist_call,
    payload_digest,
    prompt_fingerprint,
)
from models import AiAssistLog

TEST_MARK = "单元测试专用"
SCENE = f"profile_coach{TEST_MARK}"
RAW_TEXT = "我叫张三，电话 13800138000，住在张江，预算 3500 元"


@pytest.fixture(autouse=True)
async def clean_assist_logs(db):
    """用例结束后删掉本用例写入的日志行（scene 里带测试标记）。"""
    yield
    await AiAssistLog.filter(scene__contains=TEST_MARK).delete()


def test_prompt_fingerprint_is_stable_and_sensitive():
    """同一段提示词指纹稳定，不同提示词指纹不同；空值返回 None。"""
    first = prompt_fingerprint("请阅读租客档案后给出追问与建议。")
    assert first == prompt_fingerprint("请阅读租客档案后给出追问与建议。")
    assert first != prompt_fingerprint("请阅读租客档案后给出解读简报。")
    assert len(first) == HASH_LENGTH == 64
    int(first, 16)  # 必须是十六进制
    assert prompt_fingerprint(None) is None
    assert prompt_fingerprint("") is None


def test_payload_digest_is_normalized_and_not_plaintext():
    """输入摘要与 key 顺序无关，不同输入摘要不同，摘要不等于原文。"""
    first = payload_digest({"budget": 3500, "self_intro": RAW_TEXT})
    second = payload_digest({"self_intro": RAW_TEXT, "budget": 3500})
    assert first == second
    assert len(first) == HASH_LENGTH
    assert first != payload_digest({"budget": 3000, "self_intro": RAW_TEXT})
    assert payload_digest(None) is None
    assert RAW_TEXT not in first


async def test_helper_writes_one_row_with_expected_fields(db):
    """helper 成功写一行，场景/关联/模型/耗时/token/状态/采纳/时间都正确。"""
    payload = {"profile": {"nickname": "小宋", "rent_budget": 3500},
               "preference": {"budget_min": 1500, "budget_required": "必须"}}
    prompt_text = "请阅读租客档案后给出追问与建议。"

    row = await log_assist_call(
        scene=SCENE,
        member_id=1,
        prompt_code="PROFILE_COACH_PROMPT",
        prompt_text=prompt_text,
        model_name="deepseek-chat",
        input_payload=payload,
        latency_ms=123,
        usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        status="成功",
        adopted=True,
    )
    assert row is not None and row.id

    saved = await AiAssistLog.get(id=row.id)
    assert saved.scene == SCENE
    assert saved.member_id == 1
    assert saved.prompt_code == "PROFILE_COACH_PROMPT"
    assert saved.model_name == "deepseek-chat"
    assert saved.latency_ms == 123
    assert saved.prompt_tokens == 100
    assert saved.completion_tokens == 20
    assert saved.status == "成功"
    assert saved.adopted is True
    assert saved.error_message is None
    assert saved.prompt_hash == prompt_fingerprint(prompt_text)
    assert saved.input_digest == payload_digest(payload)
    assert saved.create_time is not None


async def test_helper_defaults_status_and_adopted(db):
    """不传状态/采纳时：默认成功、未采纳，摘要类字段为空。"""
    row = await log_assist_call(scene=SCENE)
    assert row is not None
    saved = await AiAssistLog.get(id=row.id)
    assert saved.status == "成功"
    assert saved.adopted is False
    assert saved.member_id is None
    assert saved.prompt_hash is None
    assert saved.input_digest is None
    assert saved.error_message is None


async def test_input_digest_is_sha256_and_not_plaintext(db):
    """input_digest 是 64 位十六进制 sha256，且不等于输入的原文。"""
    payload = {"self_intro": RAW_TEXT, "nested": [1, 2, {"k": "中文"}]}
    row = await log_assist_call(scene=SCENE, prompt_text=RAW_TEXT, input_payload=payload)
    saved = await AiAssistLog.get(id=row.id)

    assert len(saved.input_digest) == HASH_LENGTH
    int(saved.input_digest, 16)
    assert saved.input_digest == payload_digest(payload)
    assert saved.input_digest != RAW_TEXT
    assert saved.prompt_hash == prompt_fingerprint(RAW_TEXT)


async def test_usage_supports_both_dict_shapes(db):
    """token 用量同时支持 input/output 与 prompt/completion 两种字段命名。"""
    first = await log_assist_call(
        scene=SCENE, usage={"prompt_tokens": "30", "completion_tokens": 7})
    saved = await AiAssistLog.get(id=first.id)
    assert saved.prompt_tokens == 30
    assert saved.completion_tokens == 7

    second = await log_assist_call(
        scene=SCENE, usage={"input_tokens": 11, "output_tokens": 2})
    saved = await AiAssistLog.get(id=second.id)
    assert saved.prompt_tokens == 11
    assert saved.completion_tokens == 2

    third = await log_assist_call(scene=SCENE, usage=None)
    saved = await AiAssistLog.get(id=third.id)
    assert saved.prompt_tokens is None
    assert saved.completion_tokens is None


async def test_error_message_is_truncated_to_500(db):
    """失败原因按列宽截断到 500 字，状态照实记录。"""
    row = await log_assist_call(
        scene=SCENE, status="失败", error_message="错" * (ERROR_LIMIT + 300))
    assert row is not None
    saved = await AiAssistLog.get(id=row.id)
    assert saved.status == "失败"
    assert saved.error_message is not None
    assert len(saved.error_message) == ERROR_LIMIT
    assert saved.error_message.startswith("错")


async def test_only_digest_is_stored_not_raw_text(db):
    """库里只存摘要：提示词/输入里的中文原文和个人信息不会出现在日志文本列里。

    error_message 是调用方显式给的失败原因（这里不传原文），不在「摘要」范围内。
    """
    row = await log_assist_call(
        scene=SCENE,
        prompt_text=RAW_TEXT,
        input_payload={"self_intro": RAW_TEXT, "contact": "13800138000"},
    )
    assert row is not None
    saved = await AiAssistLog.get(id=row.id)

    text_columns = [
        saved.scene or "", saved.prompt_code or "", saved.prompt_hash or "",
        saved.model_name or "", saved.input_digest or "", saved.status or "",
        saved.error_message or "",
    ]
    blob = "\n".join(text_columns)
    assert "张三" not in blob
    assert "13800138000" not in blob
    assert RAW_TEXT not in blob


async def test_write_failure_is_swallowed(db, monkeypatch):
    """写库失败只返回 None，不把异常抛给调用方（日志不能影响主流程）。"""
    async def boom(self):
        raise RuntimeError("database is down")

    monkeypatch.setattr(AiAssistLog, "save", boom)
    result = await log_assist_call(scene=SCENE, prompt_text="任意提示词")
    assert result is None