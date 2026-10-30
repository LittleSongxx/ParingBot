"""AI 辅助能力调用日志（Phase 0 最小实现）。

资料教练、匹配解读官这类辅助能力每次调用模型，都应该留下一条可审计的记录：
用了哪个场景、哪条提示词、哪个模型、耗时多少、token 用了多少、成功还是失败、
结果有没有被采纳。

这里刻意只存「摘要」：
- prompt_text 算 sha256（64 位十六进制）存 prompt_hash；
- input_payload 规范化 JSON 后算 sha256 存 input_digest；
- 原文（自我介绍、偏好、联系方式等 PII）一律不落库，想复现原始输入要回到业务表。

写日志是旁路：数据库抖动、字段超长都不应该影响正在跑的主流程，所以写库失败
只打印一行到控制台并返回 None，不向上抛异常。
"""

import hashlib
import json

from models import AiAssistLog

# sha256 十六进制摘要长度，和表里 char(64) 两列一致
HASH_LENGTH = 64
# 失败原因截断长度，和 ai_assist_log.error_message varchar(500) 一致
ERROR_LIMIT = 500


def prompt_fingerprint(text: str | None) -> str | None:
    """提示词全文的 sha256 指纹（64 位十六进制）。空值返回 None。"""
    if not text:
        return None
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def payload_digest(payload) -> str | None:
    """输入载荷规范化 JSON 后的 sha256；只用于判断「是不是同一份输入」，不存原文。

    规范化规则：key 排序、紧凑分隔符、ensure_ascii=False（同样的中文输入在任何
    机器上得到同一个摘要）。无法 JSON 序列化的对象退回 str()，同样只参与摘要。
    """
    if payload is None:
        return None
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _to_int(value) -> int | None:
    """把数字/数字字符串转成 int，转不了或布尔值返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _short(value, limit: int) -> str | None:
    """字符串字段按列宽截断；空值返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit]


def _token_usage(usage) -> tuple[int | None, int | None]:
    """把不同来源的用量字段统一成 (prompt_tokens, completion_tokens)。

    支持两类写法：input_tokens/output_tokens（LangChain usage_metadata 风格）
    与 prompt_tokens/completion_tokens（OpenAI usage 风格）；传入对象时按属性名读。
    """
    if usage is None:
        return None, None

    def pick(*names):
        if isinstance(usage, dict):
            for name in names:
                if usage.get(name) is not None:
                    return usage[name]
            return None
        for name in names:
            value = getattr(usage, name, None)
            if value is not None:
                return value
        return None

    prompt_tokens = _to_int(pick("prompt_tokens", "input_tokens"))
    completion_tokens = _to_int(pick("completion_tokens", "output_tokens"))
    return prompt_tokens, completion_tokens


async def log_assist_call(*, scene: str, member_id: int | None = None,
                          prompt_code: str | None = None, prompt_text: str | None = None,
                          model_name: str | None = None, input_payload=None,
                          latency_ms: int | None = None, usage=None,
                          status: str = "成功", adopted: bool = False,
                          error_message: str | None = None) -> AiAssistLog | None:
    """写一条 AI 辅助调用日志，返回写入的行；写库失败时返回 None。

    参数：
    - scene：场景编码，例如 profile_coach / match_brief（必填）；
    - prompt_text / input_payload：只参与摘要，原文不落库；
    - usage：token 用量字典，两种字段命名都认；
    - adopted：这次结果有没有被用户采纳，给后续效果评估用。
    """
    prompt_tokens, completion_tokens = _token_usage(usage)
    row = AiAssistLog(
        scene=_short(scene, 32) or "unknown",
        member_id=_to_int(member_id),
        prompt_code=_short(prompt_code, 64),
        prompt_hash=prompt_fingerprint(prompt_text),
        model_name=_short(model_name, 128),
        input_digest=payload_digest(input_payload),
        latency_ms=_to_int(latency_ms),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        status=_short(status, 16) or "成功",
        adopted=bool(adopted),
        error_message=_short(error_message, ERROR_LIMIT),
    )
    try:
        await row.save()
    except Exception as exc:  # noqa: BLE001
        # 日志是旁路：写不进去也不能影响主流程，控制台留一行方便排查即可
        print(f"[AI调用日志] 写库失败，已忽略：{type(exc).__name__}: {exc}")
        return None
    return row