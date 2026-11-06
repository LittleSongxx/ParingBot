#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匹配质量成对 judge：交付候选 vs 三档对照（quality-v1-2026-11-06 / judge-v1）。

对外口径（eval/quality_spec.py METRICS["match_quality"]）：
* 三档对照，每档独立采样：near_miss（同 run 通过审核/被容量截断但未交付）、
  rejected（同 run audit_status 否决）、random（其他 run 的候选，随机池基线）；
* judge 材料严格白名单：复用 eval/pairwise_quality.py 的 safe_person /
  assert_safe_material，材料里不出现 delivered/audit_status/screen_score/evidence/
  rank/*_role 等系统元数据（fail-closed：写 prompt 与写 materials 前都断言）；
* 每个 pair 做双向调用（A/B 与 B/A 各一次），同一身份才算一致；双向不一致不进入胜率；
* 多 judge（--judge-model 可重复或逗号分隔）：逐 judge 报告 + 多数票聚合 +
  Bradley-Terry（eval/lib/stats.py）；
* 统计：Wilson + Clopper-Pearson CI（eval/lib/stats.py），position consistency，
  by_stratum / by_judge；n_errors/n_pairs > 20% 或 position_consistency < 0.85 → usable=false。

代理评审（LLM judge）不是人工真值；E2 证据，只有人工校准（kappa>=0.6）后
才能按 quality_spec.claim_gate 对外申报。

CLI:
  python eval/quality_pairwise.py --bundle bundle.json --out match-quality.json \
      [--emit-materials materials.json] [--limit-pairs 12] [--seed 20261106] \
      [--env-file .env.eval] [--judge-model qwen3.7-plus] [--dry-run] \
      [--fake-verdicts fake.json]

可编程 API（集成测试/报告复用）：
  build(bundle, *, limit_pairs=12, seed=...) -> list[pair]
  build_materials(pairs) -> {"protocol","pairs","key"}
  judge_pairs(pairs, *, models, judge_fn=None, env=None, fake_verdicts=None) -> list[detail]
  summarize(details, *, models=None, seed=..., limit_pairs=..., dry_run=False, ...) -> report
  run(bundle, *, models=None, judge_fn=None, ..., dry_run=False, fake_verdicts=None) -> report
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import pairwise_quality  # noqa: E402
import quality_spec  # noqa: E402
from judge import PAIR_PROMPT  # noqa: E402
from lib import stats as statsmod  # noqa: E402
from lib.env import load_env  # noqa: E402

PROTOCOL = quality_spec.PROTOCOL_VERSION
JUDGE_VERSION = quality_spec.JUDGE_VERSION
DEFAULT_SEED = 20261106
DEFAULT_LIMIT_PAIRS = 12
DEFAULT_MODEL = "qwen3.7-plus"
DEFAULT_ENV = REPO / ".env.eval"
STRATA = ("near_miss", "rejected", "random")
PASS_STATUSES = ("通过", "已通过", "pass", "approved", "已通过审核")
REJECT_STATUSES = ("否决", "已驳回", "reject", "rejected", "拒绝")
TIE_WEIGHT = 0.5
MAX_ERROR_RATE = 0.20
POSITION_CONSISTENCY_MIN = float(quality_spec.JUDGE_GATES.get("position_consistency_min", 0.85))

__all__ = [
    "build", "build_materials", "judge_pairs", "summarize", "run", "main",
    "load_fake_verdicts", "_call_judge", "STRATA", "DEFAULT_SEED",
    "DEFAULT_LIMIT_PAIRS", "PROTOCOL", "JUDGE_VERSION",
]


# ---------------------------------------------------------------------------
# 基础小工具
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_int(value):
    """把 bundle 里可能是字符串的数字统一成 int；失败返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "是", "通过", "delivered")


def _rng(seed, *parts) -> random.Random:
    """确定性 RNG：同一 (seed, 维度, 标识) 永远得到同一随机流（跨进程稳定）。"""
    material = ":".join([str(seed)] + [str(part) for part in parts])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _normalize_models(value) -> list:
    """--judge-model 支持重复参数与逗号分隔；去重保序。"""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    models = []
    for item in items:
        for part in str(item).split(","):
            name = part.strip()
            if name and name not in models:
                models.append(name)
    return models


# ---------------------------------------------------------------------------
# bundle 解析：delivered / near_miss / rejected / random
# ---------------------------------------------------------------------------


def _runs(bundle) -> list:
    return [run for run in ((bundle or {}).get("runs") or []) if isinstance(run, dict)]


def _candidate_member_id(candidate) -> int | None:
    for key in ("id", "candidate_member_id", "member_id"):
        value = _as_int((candidate or {}).get(key))
        if value is not None:
            return value
    return None


def _candidate_key(run_index: int, cand_index: int, candidate: dict) -> str:
    """候选的稳定标识：优先成员 id（跨 run 可去重），退化到行 id / 位置。"""
    member_id = _candidate_member_id(candidate)
    if member_id is not None:
        return f"m{member_id}"
    row_id = _as_int((candidate or {}).get("candidate_row_id"))
    if row_id is not None:
        return f"row{row_id}"
    return f"r{run_index}c{cand_index}"


def _external_id(key) -> object:
    """内部 key（m861/row77）转回对外 id（861/77/字符串）。"""
    text = str(key)
    if text.startswith("m") and text[1:].isdigit():
        return int(text[1:])
    if text.startswith("row") and text[3:].isdigit():
        return int(text[3:])
    return text


def _is_delivered(candidate) -> bool:
    candidate = candidate or {}
    if _truthy(candidate.get("delivered")):
        return True
    rank = _as_int(candidate.get("delivered_rank"))
    return rank is not None and rank > 0


def _stratum_of_non_delivered(candidate) -> str | None:
    """同 run 未交付候选的档位：rejected / near_miss；无法归类返回 None。"""
    candidate = candidate or {}
    status = str(candidate.get("audit_status") or "").strip()
    if status in REJECT_STATUSES:
        return "rejected"
    if (_truthy(candidate.get("passed")) or _truthy(candidate.get("truncated"))
            or status in PASS_STATUSES):
        return "near_miss"
    if candidate.get("reject_code"):
        return "rejected"
    return None


def _is_applicant(candidate, applicant_id) -> bool:
    if applicant_id is None:
        return False
    return _candidate_member_id(candidate) == applicant_id


def _build_delivered_items(runs: list) -> list:
    items = []
    for run_index, run in enumerate(runs):
        applicant = run.get("applicant") or {}
        applicant_id = _candidate_member_id(applicant)
        candidates = [item for item in (run.get("candidates") or []) if isinstance(item, dict)]
        for cand_index, candidate in enumerate(candidates):
            if not _is_delivered(candidate):
                continue
            items.append({
                "run_index": run_index,
                "run": run,
                "candidate": candidate,
                "candidate_key": _candidate_key(run_index, cand_index, candidate),
                "member_id": _candidate_member_id(candidate),
                "applicant_id": applicant_id,
            })
    return items


def _global_candidates(runs: list) -> list:
    """随机池：所有 run 的候选（按成员 id 去重，保留首次出现）。"""
    pool = []
    seen = set()
    for run_index, run in enumerate(runs):
        for cand_index, candidate in enumerate(run.get("candidates") or []):
            if not isinstance(candidate, dict):
                continue
            identity = _candidate_member_id(candidate)
            if identity is None:
                identity = _as_int(candidate.get("candidate_row_id"))
            if identity is not None:
                if identity in seen:
                    continue
                seen.add(identity)
            pool.append({
                "run_index": run_index,
                "run": run,
                "candidate": candidate,
                "key": _candidate_key(run_index, cand_index, candidate),
                "member_id": _candidate_member_id(candidate),
            })
    return pool


def _same_run_control_options(item: dict, stratum: str) -> list:
    """near_miss / rejected：同一 run 内未交付候选。"""
    run = item["run"]
    options = []
    for cand_index, candidate in enumerate(run.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if candidate is item["candidate"]:
            continue
        if _is_delivered(candidate):
            continue
        if _stratum_of_non_delivered(candidate) != stratum:
            continue
        if _candidate_member_id(candidate) == item["member_id"]:
            continue
        if _is_applicant(candidate, item["applicant_id"]):
            continue
        options.append({
            "run_index": item["run_index"],
            "run": run,
            "candidate": candidate,
            "key": _candidate_key(item["run_index"], cand_index, candidate),
            "member_id": _candidate_member_id(candidate),
        })
    return options


def _random_control_options(item: dict, global_candidates: list) -> list:
    """random：其他 run 的候选（随机池基线，按成员 id 去重后抽样）。"""
    options = []
    for entry in global_candidates:
        if entry["run_index"] == item["run_index"]:
            continue
        if entry["key"] == item["candidate_key"]:
            continue
        if entry["member_id"] is not None and entry["member_id"] == item["member_id"]:
            continue
        if _is_applicant(entry["candidate"], item["applicant_id"]):
            continue
        options.append(entry)
    return options


def _build_stratum_pool(stratum: str, delivered_items: list, global_candidates: list,
                        seed: int) -> list:
    """每个档位独立采样：先为每个 delivered 候选选一个对照，形成该档候选池。"""
    pool = []
    seen = set()
    for item in delivered_items:
        if stratum == "random":
            options = _random_control_options(item, global_candidates)
        else:
            options = _same_run_control_options(item, stratum)
        if not options:
            continue
        rng = _rng(seed, stratum, item["candidate_key"], "control")
        control = options[rng.randrange(len(options))]
        dedupe = (item["run_index"], item["candidate_key"], control["key"])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        pool.append({"stratum": stratum, "delivered": item, "control": control})
    return pool


def _allocate_quotas(pools: dict, limit: int) -> dict:
    """按档轮转分配配额（near_miss 优先），空缺档位的配额自动让给其他档。"""
    quotas = {stratum: 0 for stratum in STRATA}
    remaining = max(0, int(limit))
    while remaining > 0:
        progressed = False
        for stratum in STRATA:
            if remaining <= 0:
                break
            if quotas[stratum] < len(pools.get(stratum) or []):
                quotas[stratum] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return quotas


def _sample_pool(pool: list, quota: int, seed: int, stratum: str) -> list:
    quota = max(0, min(int(quota), len(pool)))
    if quota <= 0:
        return []
    if quota >= len(pool):
        return list(pool)
    rng = _rng(seed, stratum, "sample")
    picked = sorted(rng.sample(range(len(pool)), quota))
    return [pool[index] for index in picked]


def _make_pair(entry: dict, seed: int) -> dict:
    stratum = entry["stratum"]
    item = entry["delivered"]
    control = entry["control"]
    run = item["run"]
    run_id = (run.get("run") or {}).get("id")
    if run_id is None:
        run_id = item["run_index"]
    pair_id = f"{stratum}-r{run_id}-d{item['candidate_key']}-c{control['key']}"
    rng = _rng(seed, stratum, item["candidate_key"], control["key"], "side")
    delivered_side = "A" if rng.random() < 0.5 else "B"
    if delivered_side == "A":
        candidate_a, candidate_b = item["candidate"], control["candidate"]
    else:
        candidate_a, candidate_b = control["candidate"], item["candidate"]
    return {
        "pair_id": pair_id,
        "stratum": stratum,
        "run_id": run_id,
        "delivered_id": _external_id(item["candidate_key"]),
        "control_id": _external_id(control["key"]),
        "delivered_side": delivered_side,
        "applicant": pairwise_quality.safe_person(run.get("applicant") or {}),
        "candidate_a": pairwise_quality.safe_person(candidate_a),
        "candidate_b": pairwise_quality.safe_person(candidate_b),
    }


def build(bundle: dict, *, limit_pairs: int = DEFAULT_LIMIT_PAIRS,
          seed: int = DEFAULT_SEED) -> list:
    """从 quality bundle 构建成对材料（三档分层采样，确定性可复现）。

    返回 list[pair]：pair_id, stratum, run_id, delivered_id, control_id,
    delivered_side, applicant/candidate_a/candidate_b（全部 safe_person 白名单）。
    每档独立采样；limit_pairs 按档轮转分配，数量不足的档位把配额让给其他档。
    """
    runs = _runs(bundle)
    delivered_items = _build_delivered_items(runs)
    if not delivered_items:
        return []
    global_candidates = _global_candidates(runs)
    pools = {stratum: _build_stratum_pool(stratum, delivered_items, global_candidates, seed)
             for stratum in STRATA}
    available = sum(len(pool) for pool in pools.values())
    limit = int(limit_pairs) if limit_pairs is not None else DEFAULT_LIMIT_PAIRS
    if limit <= 0 or limit > available:
        limit = available
    quotas = _allocate_quotas(pools, limit)
    pairs = []
    for stratum in STRATA:
        for entry in _sample_pool(pools[stratum], quotas[stratum], seed, stratum):
            pairs.append(_make_pair(entry, seed))
    if pairs:
        build_materials(pairs)  # fail-closed：白名单闸门
    return pairs


def build_materials(pairs: list) -> dict:
    """生成人工盲评材料（--emit-materials）：pairs 去系统元数据 + 内部 key。

    材料统一过 pairwise_quality.safe_person；写出前整体过
    pairwise_quality.assert_safe_material（泄漏即 raise，fail-closed）。
    """
    material_pairs = []
    key = {}
    for pair in pairs or []:
        pair = pair or {}
        material_pairs.append({
            "pair_id": pair.get("pair_id"),
            "stratum": pair.get("stratum"),
            "applicant": pairwise_quality.safe_person(pair.get("applicant") or {}),
            "candidate_a": pairwise_quality.safe_person(pair.get("candidate_a") or {}),
            "candidate_b": pairwise_quality.safe_person(pair.get("candidate_b") or {}),
        })
        key[str(pair.get("pair_id"))] = {
            "delivered_side": pair.get("delivered_side"),
            "delivered_id": pair.get("delivered_id"),
            "control_id": pair.get("control_id"),
            "stratum": pair.get("stratum"),
        }
    payload = {"protocol": PROTOCOL, "pairs": material_pairs, "key": key}
    pairwise_quality.assert_safe_material(payload)
    return payload


# ---------------------------------------------------------------------------
# judge 调用（可注入；默认走 OpenAI 兼容 /chat/completions）
# ---------------------------------------------------------------------------


def _judge_prompt(pair: dict, swapped: bool) -> str:
    """构造单向 prompt：swapped=True 时交换 A/B（位置偏差检测的反向调用）。"""
    applicant = pair.get("applicant") or {}
    if swapped:
        candidate_a, candidate_b = pair.get("candidate_b") or {}, pair.get("candidate_a") or {}
    else:
        candidate_a, candidate_b = pair.get("candidate_a") or {}, pair.get("candidate_b") or {}
    payload = {"applicant": applicant, "candidate_a": candidate_a, "candidate_b": candidate_b}
    pairwise_quality.assert_safe_material(payload)  # fail-closed：每次发 prompt 前校验
    return PAIR_PROMPT.format(
        applicant=json.dumps(applicant, ensure_ascii=False),
        candidate_a=json.dumps(candidate_a, ensure_ascii=False),
        candidate_b=json.dumps(candidate_b, ensure_ascii=False),
    )


def _loads_json_or_none(text):
    cleaned = re.sub(r"```(?:json)?", "", str(text or "")).strip("` \n")
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except (TypeError, ValueError):
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, cleaned, re.S)
        if not match:
            continue
        try:
            return json.loads(match.group(0))
        except (TypeError, ValueError):
            continue
    return None


def _normalize_winner(raw) -> str:
    """把 judge 返回的 winner 归一到 A/B/tie；无法识别时 raise ValueError。"""
    if isinstance(raw, dict):
        return _normalize_winner(raw.get("winner") or raw.get("choice") or raw.get("result"))
    if raw is None:
        raise ValueError("judge 未返回 winner")
    text = str(raw).strip()
    if not text:
        raise ValueError("judge 返回空 winner")
    compact = text.strip(" .。:：!！\"'`").strip()
    lowered = compact.lower()
    if lowered in ("tie", "draw", "equal", "same", "equal_score", "平局", "相同", "一样", "打平"):
        return "tie"
    upper = compact.upper()
    if upper in ("A", "B"):
        return upper
    tokens = re.findall(r"(?<![A-Za-z])[AB](?![A-Za-z])", upper)
    unique = sorted(set(tokens))
    if len(unique) == 1:
        return unique[0]
    raise ValueError(f"judge winner 无法解析：{text[:80]}")


def _parse_judge_response(payload) -> dict:
    """解析 judge 输出为 {"winner": A/B/tie, "reason": 一句话}。"""
    data = payload
    if isinstance(data, str):
        parsed = _loads_json_or_none(data)
        if parsed is None:
            return {"winner": _normalize_winner(data), "reason": ""}
        data = parsed
    if isinstance(data, list):
        if not data:
            raise ValueError("judge 返回空数组")
        first = next((item for item in data if isinstance(item, dict)), data[0])
        return _parse_judge_response(first)
    if not isinstance(data, dict):
        return {"winner": _normalize_winner(data), "reason": ""}
    winner_raw = None
    for name in ("winner", "choice", "result", "verdict", "label", "answer"):
        if data.get(name) is not None:
            winner_raw = data[name]
            break
    if winner_raw is None:
        raise ValueError("judge 响应缺少 winner/choice 字段")
    reason = data.get("reason") or data.get("rationale") or data.get("explanation") or ""
    return {"winner": _normalize_winner(winner_raw), "reason": str(reason)[:500]}


def _post_chat(base_url: str, api_key: str, payload: dict) -> str:
    """POST /chat/completions；部分网关不支持 response_format 时自动重试一次。"""
    request_payload = dict(payload)
    response = None
    for attempt_index in (0, 1):
        request = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as handle:
                response = json.loads(handle.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if attempt_index == 0 and exc.code == 400 and "response_format" in request_payload:
                request_payload.pop("response_format", None)
                continue
            raise
    if response is None:
        raise RuntimeError("judge 请求失败（无响应）")
    choices = response.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    content = message.get("content") or message.get("reasoning_content") or ""
    if not content:
        raise RuntimeError("judge 返回空内容")
    return content


def _call_judge(prompt: str, model: str, env: dict) -> dict:
    """模块级默认 judge 调用（测试可 monkeypatch 或通过 judge_fn 注入）。"""
    env = env or {}
    base_url = str(env.get("EVAL_JUDGE_BASE_URL") or "")
    api_key = str(env.get("EVAL_JUDGE_API_KEY") or "")
    if not base_url or not api_key:
        raise RuntimeError("缺少 EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 配置")
    payload = {"model": model, "temperature": 0.0, "max_tokens": 1200,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": prompt}]}
    content = _post_chat(base_url, api_key, payload)
    return _parse_judge_response(content)


def _invoke_judge(judge_fn, prompt: str, model: str, env: dict):
    """兼容注入函数的 1/2/3 参数签名：(prompt)/(prompt, model)/(prompt, model, env)。"""
    try:
        signature = inspect.signature(judge_fn)
        parameters = signature.parameters.values()
        positional = [item for item in parameters
                      if item.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                       inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        variadic = any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters)
    except (TypeError, ValueError):
        positional, variadic = [], True
    if variadic or len(positional) >= 3:
        return judge_fn(prompt, model, env)
    if len(positional) == 2:
        return judge_fn(prompt, model)
    if len(positional) == 1:
        return judge_fn(prompt)
    return judge_fn()


def _normalize_direction(value) -> str:
    if value is None:
        return "forward"
    text = str(value).strip().lower()
    if text in ("backward", "back", "bwd", "swap", "swapped", "reverse", "reversed",
                "b", "1", "后向", "反向"):
        return "backward"
    return "forward"


def load_fake_verdicts(source) -> dict:
    """读 --fake-verdicts：离线重放 judge 判决（测试/联调用，不联网）。

    支持格式（推荐 list）：
      [{"pair_id": "...", "model": "qwen3.7-plus", "direction": "forward|backward",
        "winner": "A|B|tie", "reason": "..."}]
    也接受 {"verdicts": [...]}、{"<pair_id>|forward": "A"}、
    {"<pair_id>": {"forward": "A", "backward": "B"}}。
    model 省略 = 匹配任意 judge；direction 省略 = forward；缺失的反向记录记为 error
    （不自动镜像，避免伪造位置一致性）。
    返回 {(model|None, pair_id, direction): {"winner","reason"}}。
    """
    if isinstance(source, dict) and source and all(
            isinstance(key, tuple) and len(key) == 3 for key in source):
        return dict(source)  # 已经是解析后的 records
    if isinstance(source, (str, Path)):
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        raw = source
    records: dict = {}

    def add(pair_id, direction, winner, reason="", model=None):
        if pair_id is None:
            return
        key = (str(model) if model not in (None, "") else None,
               str(pair_id), _normalize_direction(direction))
        records[key] = {"winner": winner, "reason": str(reason or "")}

    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                add(row.get("pair_id"), row.get("direction"), row.get("winner"),
                    row.get("reason"), row.get("model"))
        return records
    if not isinstance(raw, dict):
        raise ValueError("fake verdicts 格式不支持（需要 list 或 dict）")
    verdicts = raw.get("verdicts")
    if isinstance(verdicts, list):
        for row in verdicts:
            if isinstance(row, dict):
                add(row.get("pair_id"), row.get("direction"), row.get("winner"),
                    row.get("reason"), row.get("model"))
        return records
    for pair_id, value in raw.items():
        if isinstance(pair_id, tuple):
            continue
        if "|" in str(pair_id):
            pid, _, direction = str(pair_id).partition("|")
            if isinstance(value, dict):
                add(pid, direction, value.get("winner"), value.get("reason"))
            else:
                add(pid, direction, value)
            continue
        if isinstance(value, dict):
            model = value.get("model")
            forward = value.get("forward")
            backward = value.get("backward")
            if forward is not None:
                if isinstance(forward, dict):
                    add(pair_id, "forward", forward.get("winner"), forward.get("reason"), model)
                else:
                    add(pair_id, "forward", forward, "", model)
            if backward is not None:
                if isinstance(backward, dict):
                    add(pair_id, "backward", backward.get("winner"), backward.get("reason"), model)
                else:
                    add(pair_id, "backward", backward, "", model)
        else:
            add(pair_id, "forward", value)
    return records


def _lookup_fake(records: dict, model: str, pair_id, direction: str):
    if pair_id is None:
        return None
    pid = str(pair_id)
    for key in ((model, pid, direction), (None, pid, direction)):
        if key in records:
            return records[key]
    # 宽松：fake 文件只给了一个 judge 时，允许按 pair+direction 匹配。
    candidates = [record for (record_model, record_pair, record_direction), record
                  in records.items()
                  if record_pair == pid and record_direction == direction
                  and record_model not in (None, model)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _judge_once(pair: dict, model: str, *, swapped: bool, judge_fn=None,
                env=None, fake_records=None) -> dict:
    direction = "backward" if swapped else "forward"
    if fake_records is not None:
        record = _lookup_fake(fake_records, model, pair.get("pair_id"), direction)
        if record is None:
            return {"winner": None, "reason": "", "error": "fake verdict missing"}
        try:
            winner = _normalize_winner(record.get("winner"))
        except ValueError as exc:
            return {"winner": None, "reason": str(record.get("reason") or ""),
                    "error": str(exc)}
        return {"winner": winner, "reason": str(record.get("reason") or "")}
    prompt = _judge_prompt(pair, swapped)
    fn = judge_fn if judge_fn is not None else _call_judge
    try:
        payload = _invoke_judge(fn, prompt, model, env or {})
        parsed = _parse_judge_response(payload)
        return {"winner": parsed["winner"], "reason": parsed["reason"]}
    except Exception as exc:  # noqa: BLE001 - 单次 judge 失败不崩溃，计入 n_errors
        return {"winner": None, "reason": "", "error": f"{type(exc).__name__}: {exc}"}


def _judge_valid(judge: dict) -> bool:
    if not isinstance(judge, dict):
        return False
    for direction in ("forward", "backward"):
        item = judge.get(direction) or {}
        if item.get("error") or item.get("winner") not in ("A", "B", "tie"):
            return False
    return True


def _choice_of(verdict: dict, pair: dict, *, swapped: bool):
    """把单次 verdict 归一成 'delivered'/'control'/'tie'（无法判定返回 None）。"""
    if not isinstance(verdict, dict) or verdict.get("error"):
        return None
    winner = verdict.get("winner")
    if winner == "tie":
        return "tie"
    if winner not in ("A", "B"):
        return None
    delivered_side = pair.get("delivered_side")
    if delivered_side not in ("A", "B"):
        return None
    # 反向调用时 A/B 位置互换：delivered 在该次调用里落在另一侧。
    effective_side = delivered_side if not swapped else (
        "B" if delivered_side == "A" else "A")
    return "delivered" if winner == effective_side else "control"


def _majority_choice(judges: dict) -> str:
    """多数票：返回 delivered/control/tie/unresolved/inconsistent/error。"""
    votes = []
    any_valid = False
    for judge in (judges or {}).values():
        if not _judge_valid(judge):
            continue
        any_valid = True
        choice = judge.get("choice")
        if choice in ("delivered", "control", "tie"):
            votes.append(choice)
    if not votes:
        return "inconsistent" if any_valid else "error"
    counts = {name: votes.count(name) for name in ("delivered", "control", "tie")}
    best = max(counts.values())
    leaders = [name for name, count in counts.items() if count == best]
    if len(leaders) == 1:
        return leaders[0]
    return "unresolved"


def _flat_verdicts(judges: dict) -> list:
    flat = []
    for model, judge in (judges or {}).items():
        for direction in ("forward", "backward"):
            item = (judge or {}).get(direction) or {}
            flat.append({
                "model": model,
                "direction": direction,
                "winner": item.get("winner"),
                "reason": item.get("reason") or "",
                "error": item.get("error"),
            })
    return flat


def judge_pairs(pairs: list, *, models=None, judge_fn=None, env=None,
                fake_verdicts=None) -> list:
    """对每个 pair 做双向 judge 调用，返回带 verdicts 明细的 pair 列表。"""
    model_list = _normalize_models(models) or [DEFAULT_MODEL]
    records = load_fake_verdicts(fake_verdicts) if fake_verdicts is not None else None
    details = []
    for pair in pairs or []:
        judges = {}
        for model in model_list:
            forward = _judge_once(pair, model, swapped=False, judge_fn=judge_fn,
                                  env=env, fake_records=records)
            backward = _judge_once(pair, model, swapped=True, judge_fn=judge_fn,
                                   env=env, fake_records=records)
            forward_choice = _choice_of(forward, pair, swapped=False)
            backward_choice = _choice_of(backward, pair, swapped=True)
            consistent = forward_choice is not None and forward_choice == backward_choice
            judges[model] = {
                "forward": forward,
                "backward": backward,
                "forward_choice": forward_choice,
                "backward_choice": backward_choice,
                "consistent": consistent,
                "choice": forward_choice if consistent else None,
            }
        detail = {
            "pair_id": pair.get("pair_id"),
            "stratum": pair.get("stratum"),
            "run_id": pair.get("run_id"),
            "delivered_id": pair.get("delivered_id"),
            "control_id": pair.get("control_id"),
            "delivered_side": pair.get("delivered_side"),
            "judges": judges,
            "verdicts": _flat_verdicts(judges),
        }
        detail["majority_choice"] = _majority_choice(judges)
        details.append(detail)
    return details


# ---------------------------------------------------------------------------
# 聚合统计
# ---------------------------------------------------------------------------


def _empty_ci() -> dict:
    return {"method": "wilson", "n": 0, "mean": None, "lo": None, "hi": None,
            "clopper_pearson": {"method": "clopper-pearson", "n": 0,
                                "mean": None, "lo": None, "hi": None}}


def _rate_ci(successes: float, n: int) -> dict:
    """比例 CI：Wilson 为主，附带 Clopper-Pearson 精确区间。"""
    if n <= 0:
        return _empty_ci()
    wilson = statsmod.wilson_ci(float(successes), int(n))
    exact = statsmod.clopper_pearson_ci(float(successes), int(n))
    return {
        "method": "wilson",
        "n": int(wilson.get("n") or 0),
        "mean": wilson.get("mean"),
        "lo": wilson.get("lo"),
        "hi": wilson.get("hi"),
        "clopper_pearson": {
            "method": "clopper-pearson",
            "n": int(exact.get("n") or 0),
            "mean": exact.get("mean"),
            "lo": exact.get("lo"),
            "hi": exact.get("hi"),
        },
    }


def _bucket_result(*, n_pairs: int, delivered: int, control: int, ties: int,
                   errors: int, inconsistent: int, observations: list,
                   dry_run: bool = False) -> dict:
    judged = 0 if dry_run else max(0, n_pairs - errors)
    resolved = delivered + control + ties
    win = delivered + TIE_WEIGHT * ties
    win_rate = round(win / resolved, 4) if resolved else None
    win_ci = _rate_ci(win, resolved)
    observation_count = len(observations)
    consistent_obs = sum(1 for flag in observations if flag)
    position_consistency = (round(consistent_obs / observation_count, 4)
                            if observation_count else None)
    position_ci = _rate_ci(consistent_obs, observation_count)
    error_rate = round(errors / n_pairs, 4) if n_pairs else 0.0
    reasons = []
    if dry_run:
        reasons.append("dry_run：未调用 judge，胜率与位置一致性不可用")
    elif n_pairs == 0:
        reasons.append("没有可构建的 pair（bundle 缺少 delivered/对照候选）")
    else:
        if error_rate > MAX_ERROR_RATE:
            reasons.append(f"judge 失败率 {error_rate:.1%} > {MAX_ERROR_RATE:.0%}"
                           f"（n_errors={errors}/{n_pairs}）")
        if observation_count and position_consistency is not None \
                and position_consistency < POSITION_CONSISTENCY_MIN:
            reasons.append(f"位置一致性 {position_consistency:.2f} < "
                           f"{POSITION_CONSISTENCY_MIN}")
        if resolved == 0:
            reasons.append("没有方向一致的可用判定（双向全部不一致或调用失败），胜率不可估")
    return {
        "n": n_pairs,
        "n_pairs": n_pairs,
        "n_pairs_judged": judged,
        "n_errors": errors,
        "error_rate": error_rate,
        "delivered_wins": delivered,
        "control_wins": control,
        "ties": ties,
        "inconsistent": inconsistent,
        "win_rate": win_rate,
        "win_rate_ci95": win_ci,
        "position_consistency": position_consistency,
        "position_consistency_ci95": position_ci,
        "n_judgements": observation_count,
        "usable": not reasons,
        "reasons": reasons,
    }


def _row(detail: dict) -> dict:
    judges = detail.get("judges") or {}
    status = detail.get("majority_choice") or _majority_choice(judges)
    if status in ("unresolved", "inconsistent"):
        status = "inconsistent"
    return {
        "pair_id": detail.get("pair_id"),
        "stratum": detail.get("stratum") or "unknown",
        "status": status,
        "judges": judges,
    }


def _aggregate_rows(rows: list, *, dry_run: bool = False) -> dict:
    n_pairs = len(rows)
    if dry_run:
        return _bucket_result(n_pairs=n_pairs, delivered=0, control=0, ties=0,
                              errors=0, inconsistent=0, observations=[], dry_run=True)
    statuses = [row.get("status") or "error" for row in rows]
    observations = []
    for row in rows:
        for judge in (row.get("judges") or {}).values():
            if _judge_valid(judge):
                observations.append(bool(judge.get("consistent")))
    return _bucket_result(
        n_pairs=n_pairs,
        delivered=statuses.count("delivered"),
        control=statuses.count("control"),
        ties=statuses.count("tie"),
        errors=statuses.count("error"),
        inconsistent=statuses.count("inconsistent"),
        observations=observations,
    )


def _judge_bucket(rows: list, model: str, *, dry_run: bool = False) -> dict:
    n_pairs = len(rows)
    if dry_run:
        return _bucket_result(n_pairs=n_pairs, delivered=0, control=0, ties=0,
                              errors=0, inconsistent=0, observations=[], dry_run=True)
    statuses = []
    observations = []
    for row in rows:
        judge = (row.get("judges") or {}).get(model)
        if not _judge_valid(judge):
            statuses.append("error")
            continue
        observations.append(bool(judge.get("consistent")))
        if judge.get("consistent"):
            statuses.append(judge.get("choice") or "inconsistent")
        else:
            statuses.append("inconsistent")
    return _bucket_result(
        n_pairs=n_pairs,
        delivered=statuses.count("delivered"),
        control=statuses.count("control"),
        ties=statuses.count("tie"),
        errors=statuses.count("error"),
        inconsistent=statuses.count("inconsistent"),
        observations=observations,
    )


def _bradley_terry(rows: list, *, dry_run: bool = False) -> dict:
    """Bradley-Terry：把 delivered 与各档对照作为选手，tie 按 0.5 拆分。"""
    if dry_run:
        return {"method": "bradley-terry-mm", "players": [], "strengths": {},
                "iterations": 0, "wins": {}, "comparisons": {}}
    wins: dict = {}
    comparisons: dict = {}
    for row in rows:
        status = row.get("status")
        if status not in ("delivered", "control", "tie"):
            continue
        delivered_player = "delivered"
        control_player = f"control:{row.get('stratum') or 'unknown'}"
        wins.setdefault(delivered_player, {}).setdefault(control_player, 0.0)
        wins.setdefault(control_player, {}).setdefault(delivered_player, 0.0)
        pair_key = f"{delivered_player}|{control_player}"
        comparisons[pair_key] = comparisons.get(pair_key, 0) + 1
        if status == "delivered":
            wins[delivered_player][control_player] += 1.0
        elif status == "control":
            wins[control_player][delivered_player] += 1.0
        else:
            wins[delivered_player][control_player] += TIE_WEIGHT
            wins[control_player][delivered_player] += TIE_WEIGHT
    if not wins:
        return {"method": "bradley-terry-mm", "players": [], "strengths": {},
                "iterations": 0, "wins": {}, "comparisons": {}}
    estimate = statsmod.bradley_terry(wins)
    return {
        "method": "bradley-terry-mm",
        "prior": 0.5,
        "players": sorted(wins),
        "strengths": estimate.get("strengths") or {},
        "iterations": int(estimate.get("iterations") or 0),
        "wins": {player: {opponent: round(value, 2)
                          for opponent, value in opponents.items()}
                 for player, opponents in wins.items()},
        "comparisons": dict(sorted(comparisons.items())),
    }


def _judge_independence(models: list, bundle_meta: dict) -> dict:
    production = []
    for item in (bundle_meta or {}).get("model_configs") or []:
        name = str((item or {}).get("model_name") or "").strip()
        if name and name not in production:
            production.append(name)
    same = [model for model in models if model in production]
    return {
        "production_models": production,
        "same_models": same,
        "independent": not same,
    }


def _sample_floor(n_pairs: int, by_stratum: dict) -> dict:
    min_pairs = int(quality_spec.SAMPLE_FLOORS.get("pairwise_min_pairs", 100))
    min_per = int(quality_spec.SAMPLE_FLOORS.get("pairwise_min_pairs_per_stratum", 20))
    per_stratum = {stratum: int((by_stratum.get(stratum) or {}).get("n_pairs") or 0)
                   for stratum in STRATA}
    return {
        "min_pairs": min_pairs,
        "min_pairs_per_stratum": min_per,
        "per_stratum": per_stratum,
        "ok": n_pairs >= min_pairs and all(count >= min_per
                                           for count in per_stratum.values()),
    }


def _warnings(n_pairs: int, overall: dict, by_stratum: dict) -> list:
    floor = _sample_floor(n_pairs, by_stratum)
    warnings = []
    if n_pairs < floor["min_pairs"]:
        warnings.append(f"样本量 {n_pairs} 对 < {floor['min_pairs']} 对设计下限"
                        "（CI 会很宽，quality_spec.claim_gate 会拦截对外申报）")
    for stratum in STRATA:
        count = floor["per_stratum"].get(stratum, 0)
        if count == 0:
            warnings.append(f"{stratum} 档没有可用对照 pair（检查 bundle 是否提供该档候选）")
        elif count < floor["min_pairs_per_stratum"]:
            warnings.append(f"{stratum} 档 {count} 对 < {floor['min_pairs_per_stratum']} 对"
                            "每档样本下限")
    error_rate = float(overall.get("error_rate") or 0.0)
    if 0 < overall.get("n_errors", 0) and error_rate <= MAX_ERROR_RATE:
        warnings.append(f"部分 judge 调用失败：{overall['n_errors']}/{n_pairs} 对"
                        f"（{error_rate:.1%}）")
    return warnings


def summarize(pair_details: list, *, models=None, seed: int = DEFAULT_SEED,
              limit_pairs: int = DEFAULT_LIMIT_PAIRS, dry_run: bool = False,
              bundle_meta: dict | None = None, env_file=None,
              judge_meta: dict | None = None) -> dict:
    """把双向 judge 明细聚合成 match_quality 报告 JSON（字段供 quality_report 消费）。"""
    details = list(pair_details or [])
    rows = [_row(detail) for detail in details]
    model_list = _normalize_models(models)
    if not model_list:
        model_list = sorted({model for row in rows
                             for model in (row.get("judges") or {})})
    if not model_list:
        model_list = [DEFAULT_MODEL]
    n_pairs = len(rows)
    overall = _aggregate_rows(rows, dry_run=dry_run)
    strata_present = {row.get("stratum") or "unknown" for row in rows}
    by_stratum = {}
    for stratum in list(STRATA) + sorted(strata_present - set(STRATA)):
        subset = [row for row in rows if (row.get("stratum") or "unknown") == stratum]
        by_stratum[stratum] = _aggregate_rows(subset, dry_run=dry_run)
    by_judge = {model: _judge_bucket(rows, model, dry_run=dry_run) for model in model_list}
    n_calls = 0
    n_call_errors = 0
    if not dry_run:
        n_calls = n_pairs * len(model_list) * 2
        for row in rows:
            for judge in (row.get("judges") or {}).values():
                for direction in ("forward", "backward"):
                    if (judge.get(direction) or {}).get("error"):
                        n_call_errors += 1
    bundle_meta = bundle_meta or {}
    independence = _judge_independence(model_list, bundle_meta)
    warnings = _warnings(n_pairs, overall, by_stratum)
    if not independence["independent"]:
        warnings.append("judge 模型与生产模型相同："
                        + "、".join(independence["same_models"])
                        + "（judge 独立性不足，仅作探索，不可支撑对外质量结论）")
    judgement = {
        "mode": "pairwise_dual_direction",
        "aggregation": "majority_vote",
        "judges": model_list,
        "judge_provider": None,
        "temperature": 0.0,
        "prompt": "eval/judge.py:PAIR_PROMPT",
        "prompt_version": JUDGE_VERSION,
        "dry_run": bool(dry_run),
        "fake_verdicts": False,
        "seed": int(seed),
        "limit_pairs": int(limit_pairs),
        "tie_weight": TIE_WEIGHT,
        "error_definition": "无任一 judge 的双向调用都成功解析的对",
        "win_rate_denominator": "方向一致的多数票判定对（tie 记 0.5）",
        "position_consistency_min": POSITION_CONSISTENCY_MIN,
        "max_error_rate": MAX_ERROR_RATE,
        "ci_methods": ["wilson", "clopper_pearson"],
        "n_calls": n_calls,
        "n_call_errors": n_call_errors,
        "env_file": str(env_file) if env_file is not None else None,
        "judge_independence": independence,
    }
    if judge_meta:
        judgement.update({key: value for key, value in judge_meta.items() if value is not None})
    return {
        "metric": "match_quality",
        "protocol": PROTOCOL,
        "judge_version": JUDGE_VERSION,
        "generated_at": _now(),
        "judgement": judgement,
        "n_pairs": n_pairs,
        "n_pairs_judged": overall["n_pairs_judged"],
        "n_errors": overall["n_errors"],
        "error_rate": overall["error_rate"],
        "delivered_wins": overall["delivered_wins"],
        "control_wins": overall["control_wins"],
        "ties": overall["ties"],
        "inconsistent": overall["inconsistent"],
        "win_rate": overall["win_rate"],
        "win_rate_ci95": overall["win_rate_ci95"],
        "position_consistency": overall["position_consistency"],
        "position_consistency_ci95": overall["position_consistency_ci95"],
        "position_consistency_n": overall["n_judgements"],
        "by_stratum": by_stratum,
        "by_judge": by_judge,
        "majority_vote": {
            "method": "majority",
            "n_pairs": n_pairs,
            "delivered": overall["delivered_wins"],
            "control": overall["control_wins"],
            "ties": overall["ties"],
            "inconsistent": overall["inconsistent"],
            "errors": overall["n_errors"],
            "win_rate": overall["win_rate"],
        },
        "bradley_terry": _bradley_terry(rows, dry_run=dry_run),
        "pairs": details,
        "materials_safe": True,
        "sample_floor": _sample_floor(n_pairs, by_stratum),
        "warnings": warnings,
        "usable": overall["usable"],
        "reasons": overall["reasons"],
        "bundle_meta": bundle_meta,
        "note": ("成对代理评审（LLM judge），不是人工真值；near_miss 是主口径对照，"
                 "rejected/random 为弱对照，胜率只说明相对质量；"
                 "对外申报需按 quality_spec.claim_gate 先做人工校准。"),
    }


# ---------------------------------------------------------------------------
# 编排 / CLI
# ---------------------------------------------------------------------------


def _dry_detail(pair: dict) -> dict:
    return {
        "pair_id": pair.get("pair_id"),
        "stratum": pair.get("stratum"),
        "run_id": pair.get("run_id"),
        "delivered_id": pair.get("delivered_id"),
        "control_id": pair.get("control_id"),
        "delivered_side": pair.get("delivered_side"),
        "judges": {},
        "verdicts": [],
        "majority_choice": "error",
    }


def run(bundle: dict, *, models=None, judge_fn=None, limit_pairs: int = DEFAULT_LIMIT_PAIRS,
        seed: int = DEFAULT_SEED, dry_run: bool = False, fake_verdicts=None,
        emit_materials=None, env: dict | None = None, env_file=None) -> dict:
    """构建 pair → 双向 judge → 聚合；返回 match_quality 报告 JSON。"""
    pairs = build(bundle, limit_pairs=limit_pairs, seed=seed)
    materials = build_materials(pairs)
    if emit_materials is not None:
        materials_path = Path(emit_materials)
        materials_path.parent.mkdir(parents=True, exist_ok=True)
        materials_path.write_text(json.dumps(materials, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    model_list = _normalize_models(models)
    if dry_run:
        model_list = model_list or [DEFAULT_MODEL]
        details = [_dry_detail(pair) for pair in pairs]
        judge_meta = {"dry_run": True, "fake_verdicts": False}
    elif fake_verdicts is not None:
        model_list = model_list or [DEFAULT_MODEL]
        records = load_fake_verdicts(fake_verdicts)
        details = judge_pairs(pairs, models=model_list, fake_verdicts=records)
        judge_meta = {"dry_run": False, "fake_verdicts": True}
    else:
        if env is None:
            env = load_env(Path(env_file) if env_file is not None else DEFAULT_ENV)
        model_list = model_list or _normalize_models(env.get("EVAL_JUDGE_MODEL")) \
            or [DEFAULT_MODEL]
        if judge_fn is None and not (env.get("EVAL_JUDGE_BASE_URL")
                                     and env.get("EVAL_JUDGE_API_KEY")):
            raise SystemExit("缺少 EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 配置"
                             "（或改用 --dry-run / --fake-verdicts）")
        details = judge_pairs(pairs, models=model_list, judge_fn=judge_fn, env=env)
        judge_meta = {"dry_run": False, "fake_verdicts": False,
                      "judge_provider": env.get("EVAL_JUDGE_PROVIDER")
                      or env.get("EVAL_PROVIDER")}
    return summarize(
        details,
        models=model_list,
        seed=seed,
        limit_pairs=limit_pairs,
        dry_run=dry_run,
        bundle_meta=(bundle or {}).get("meta") or {},
        env_file=env_file,
        judge_meta=judge_meta,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="匹配质量成对 judge（交付 vs near_miss/rejected/random，双向+多judge+BT）")
    parser.add_argument("--bundle", required=True, type=Path, help="quality bundle JSON")
    parser.add_argument("--out", type=Path, default=None, help="输出 match_quality 报告 JSON")
    parser.add_argument("--emit-materials", type=Path, default=None,
                        help="输出人工盲评材料 JSON（pairs + key）")
    parser.add_argument("--limit-pairs", type=int, default=DEFAULT_LIMIT_PAIRS,
                        help="pair 上限（按档轮转分配；0/负数=全部）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--judge-model", action="append", default=None,
                        help="judge 模型，可重复或逗号分隔；默认取 EVAL_JUDGE_MODEL")
    parser.add_argument("--dry-run", action="store_true",
                        help="只建 pair/材料，不调用 judge（离线）")
    parser.add_argument("--fake-verdicts", type=Path, default=None,
                        help="离线重放 judge 判决的 JSON 文件")
    args = parser.parse_args(argv)
    if not args.bundle.is_file():
        raise SystemExit(f"bundle 不存在：{args.bundle}")
    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"bundle JSON 解析失败：{exc}")
    if not isinstance(bundle, dict):
        raise SystemExit("bundle 顶层必须是 JSON object")
    report = run(
        bundle,
        models=_normalize_models(args.judge_model),
        limit_pairs=args.limit_pairs,
        seed=args.seed,
        dry_run=args.dry_run,
        fake_verdicts=args.fake_verdicts,
        emit_materials=args.emit_materials,
        env_file=args.env_file,
    )
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(json.dumps({
        "metric": report["metric"],
        "n_pairs": report["n_pairs"],
        "n_pairs_judged": report["n_pairs_judged"],
        "n_errors": report["n_errors"],
        "win_rate": report["win_rate"],
        "position_consistency": report["position_consistency"],
        "usable": report["usable"],
        "out": str(args.out) if args.out is not None else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
