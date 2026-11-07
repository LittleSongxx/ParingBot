#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容忠实度（claim 级）：把画像/运行摘要/解释文本拆成原子 claim，逐条核对原文。

CLI：
  python3 eval/content_faithfulness.py --bundle B.json --out out.json \
      [--limit-items 20] [--env-file .env.eval] [--dry-run] \
      [--emit-human-sample claims.csv] [--fake-json fake.json]

口径（与 eval/quality_spec.py 的 content_faithfulness 指标对齐）：

* judge 只输出 claim 与三分类 label（supported / contradicted / not_supported），
  并且每条 claim 必须给一条能从「原文来源」里逐字找到的 quote。模块做归一化
  包含校验：归一化后 quote 必须包含于 source_text，否则该 claim 一律降级成
  not_supported（不允许“凭印象判 supported”）。
* source_text 只由档案字段 + 动态原文拼成；画像/摘要本身不能当自己的 source
  （自证不算证据）。说明类 item（运行摘要、否决理由）用对应的结构化数据拼 source。
* 指标：faithful_rate=supported/n_claims，矛盾率=contradicted/n_claims，
  证据覆盖=有可核验 quote 的 claim 占比；区间用 Clopper-Pearson（小样本保守）。
* required_dim_coverage：画像类 item 的 7 个业务维度（年龄/预算/整洁度/门店/
  作息/租期/宠物）齐全率；非画像 item 不参与该分母。
* 确定性规则兜底（不调 judge，E0）：宠物/吸烟/预算/租期/门店五维，拿档案字段
  与画像文本对账，输出 rule_warnings；这条链路在 --dry-run 下也照常产出。
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from lib.env import load_env  # noqa: E402
from lib.rules import LEASE_TERMS, STORE_LIST, STORE_NAMES, area_of  # noqa: E402
from lib.stats import clopper_pearson_ci  # noqa: E402
import quality_spec  # noqa: E402

METRIC = "content_faithfulness"
PROTOCOL = quality_spec.PROTOCOL_VERSION
JUDGE_VERSION = quality_spec.JUDGE_VERSION
DEFAULT_ENV = EVAL_DIR.parent / ".env.eval"

SAMPLE_SEED = 20261106
JUDGE_BATCH = 2
JUDGE_TIMEOUT = 120
JUDGE_MAX_TOKENS = 8192
LABELS = ("supported", "contradicted", "not_supported")
REQUIRED_DIMS = ("age", "budget", "tidiness", "store", "schedule", "lease", "pet")
DIM_ZH = {
    "age": "年龄", "budget": "预算", "tidiness": "整洁度", "store": "门店",
    "schedule": "作息", "lease": "租期", "pet": "宠物态度",
}
# 单条 claim 的人工校准 CSV 列（task-6 固定契约，不要改）
HUMAN_SAMPLE_COLUMNS = ("claim_id", "item_id", "claim", "judge_label",
                        "judge_quote", "source_excerpt")
# 不能出现在发给 judge 的材料里的系统元数据字段（self_check 也扫这一组）
FORBIDDEN_MATERIAL_KEYS = frozenset({
    "delivered", "delivered_rank", "audit_status", "screen_score", "evidence",
    "passed", "truncated", "candidate_row_id", "found_round", "relax_note",
    "audit_round", "rank", "deliverable_passed_count", "delivered_to_user",
    "truncated_count",
})
# quote 归一化后至少要有这么多字符才算“有证据”（防单字碰巧命中）
MIN_QUOTE_CHARS = 2
# judge 调用失败率超过这个比例就判 unusable
MAX_JUDGE_ERROR_RATE = 0.2

CONTENT_PROMPT_HEADER = """你是内容忠实度审核员。下面每条 item 含：
- item_id：条目编号；
- kind：条目类型（applicant_portrait/candidate_portrait=画像；run_summary=运行摘要；reject_reason=否决理由）；
- content：待核内容；
- source_text：唯一可信的原文来源（档案字段 + 动态原文 + 结构化运行数据）。

任务：把 content 拆成原子事实 claim（一条只讲一件事），逐条判断：
- supported：source_text 能直接支持；
- contradicted：source_text 与 claim 矛盾；
- not_supported：source_text 里没有依据（不能凭常识/推测补全）。
每条 claim 必须给 quote：从 source_text 里逐字复制的证据片段（不要改写、不要拼接）；
找不到证据就 quote 留空字符串。quote 会被程序做原文包含校验，找不到就降级成 not_supported。
对画像类 item（kind 以 _portrait 结尾），再判断 7 个业务维度
age/budget/tidiness/store/schedule/lease/pet 是否被 content 覆盖且有原文依据，
required_dims 填 {"age":"covered","budget":"missing",...}（covered/missing 二选一）。
非画像 item 的 required_dims 填空对象 {}。

只输出一个 JSON 对象：
{"items":[{"item_id":"...","claims":[{"claim":"...","label":"supported|contradicted|not_supported","quote":"..."}],"required_dims":{"age":"covered"}}]}
不要 markdown、不要解释、不要输出 JSON 以外的东西。

材料：
"""


# ---------------------------------------------------------------------------
# 文本归一化 / 原文包含校验
# ---------------------------------------------------------------------------
_PUNCT = set(" \t\r\n\u3000，。！？；：、,.!?;:\"'“”‘’`（）()[]{}<>【】《》〈〉-—_/\\|·~*#+=%￥$@&^")
_PUNCT.update({"－", "–", "‑"})


def normalize_text(value) -> str:
    """NFKC + 小写 + 去空白/标点：让「预算 4000 元」与「预算4000元」可比较。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    return "".join(char for char in text if char not in _PUNCT and not char.isspace())


def quote_in_source(quote, source_text) -> bool:
    """quote 归一化后是否能在 source_text 里找到（包含校验）。"""
    needle = normalize_text(quote)
    haystack = normalize_text(source_text)
    if len(needle) < MIN_QUOTE_CHARS or not haystack:
        return False
    return needle in haystack


def source_excerpt(source_text, quote, limit: int = 300) -> str:
    """给人工校准看的原文摘录：优先返回命中 quote 的那几行。"""
    text = str(source_text or "")
    needle = normalize_text(quote)
    lines = [line for line in text.splitlines() if line.strip()]
    if needle:
        hit = [line for line in lines if needle in normalize_text(line)]
        if hit:
            return "；".join(hit)[:limit]
    return text.strip()[:limit]


# ---------------------------------------------------------------------------
# 材料白名单（judge 只看用户内容 + 原文，不看系统元数据）
# ---------------------------------------------------------------------------
def _walk_keys(node, prefix: str = "") -> list:
    keys = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_walk_keys(value, prefix + str(key) + "."))
    elif isinstance(node, (list, tuple)):
        for value in node:
            keys.extend(_walk_keys(value, prefix))
    return keys


def assert_safe_material(material) -> None:
    """材料里出现系统元数据字段就报错：judge 只该看到内容与原文。"""
    forbidden = sorted(FORBIDDEN_MATERIAL_KEYS.intersection(_walk_keys(material)))
    if forbidden:
        raise ValueError("judge 材料含系统元数据字段：" + "、".join(forbidden))


def _tags_text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (list, tuple, set)):
        return "，".join(str(item).strip() for item in value if str(item).strip())
    return str(value)


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


# ---------------------------------------------------------------------------
# 从 bundle 构建 item（内容 + 原文来源）
# ---------------------------------------------------------------------------
def _run_key(run_index: int, run: dict) -> str:
    meta = run.get("run") or {}
    applicant = run.get("applicant") or {}
    for value in (applicant.get("username"), meta.get("run_no"), meta.get("id")):
        if value not in (None, ""):
            return str(value)
    return f"run{run_index}"


def person_source_lines(profile: dict) -> list[str]:
    """一位租客的「原文来源」：档案字段 + 动态原文，不包含画像内容。"""
    profile = profile or {}
    lines = []
    fields = (
        ("性别", profile.get("gender")),
        ("出生日期", profile.get("birth_date")),
        ("月租预算", _plain(profile.get("rent_budget"))),
        ("整洁度", profile.get("tidiness")),
        ("职业", profile.get("occupation")),
        ("计划租期", profile.get("lease_term")),
        ("作息", profile.get("schedule_type")),
        ("是否养宠", profile.get("has_pet")),
        ("吸烟", profile.get("smoking")),
        ("自我介绍", profile.get("self_intro")),
        ("室友期望", profile.get("roommate_expectation")),
        ("兴趣标签", _tags_text(profile.get("interest_tags"))),
    )
    for name, value in fields:
        if _plain(value).strip():
            lines.append(f"{name}：{_plain(value).strip()}")
    store_id = profile.get("store_id")
    if store_id is not None:
        name = profile.get("store_name") or STORE_NAMES.get(store_id) or ""
        area = profile.get("store_area") or area_of(store_id) or ""
        if name:
            lines.append(f"意向门店：{name}" + (f"（{area}片区）" if area else ""))
    for moment in profile.get("moments") or []:
        content = (moment or {}).get("content") if isinstance(moment, dict) else moment
        if str(content or "").strip():
            lines.append(f"动态：{str(content).strip()}")
    return lines


def preference_source_lines(preference: dict) -> list[str]:
    """把一份偏好字典摊成中文行，作为否决理由类 item 的原文来源。"""
    pref = preference or {}

    def value_of(key, default=None):
        value = pref.get(key, default)
        if value in (None, "", "None", "null", "不限"):
            return None
        return value

    lines = []
    age_min, age_max = value_of("age_min"), value_of("age_max")
    if age_min is not None or age_max is not None:
        lines.append(f"年龄要求：{age_min if age_min is not None else '不限'}-"
                     f"{age_max if age_max is not None else '不限'} 岁"
                     f"（{_plain(pref.get('age_required'))}）")
    budget_min, budget_max = value_of("budget_min"), value_of("budget_max")
    if budget_min is not None or budget_max is not None:
        lines.append(f"预算要求：{budget_min if budget_min is not None else '不限'}-"
                     f"{budget_max if budget_max is not None else '不限'} 元"
                     f"（{_plain(pref.get('budget_required'))}）")
    tidiness = value_of("tidiness_min")
    if tidiness is not None:
        lines.append(f"整洁度要求：不低于 {tidiness}（{_plain(pref.get('tidiness_required'))}）")
    scope = value_of("store_scope")
    if scope is not None:
        lines.append(f"门店要求：{scope}（{_plain(pref.get('store_required'))}）")
    schedule = _tags_text(pref.get("schedule_accept"))
    if schedule:
        lines.append(f"可接受作息：{schedule}（{_plain(pref.get('schedule_required'))}）")
    lease = value_of("lease_min")
    if lease is not None:
        lines.append(f"租期要求：不低于 {lease}（{_plain(pref.get('lease_required'))}）")
    pet = value_of("pet_accept")
    if pet is not None:
        lines.append(f"宠物态度：{pet}（{_plain(pref.get('pet_required'))}）")
    return lines


def portrait_content_text(portrait: dict) -> str:
    """画像内容：summary + 三类标签（画像本身就是待核文本）。"""
    portrait = portrait or {}
    parts = []
    summary = str(portrait.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    for key, label in (("personality_tags", "性格标签"),
                       ("lifestyle_tags", "生活方式标签"),
                       ("cohabit_need_tags", "合住需求标签")):
        value = _tags_text(portrait.get(key))
        if value:
            parts.append(f"{label}：{value}")
    return "\n".join(parts)


def run_source_text(run: dict) -> str:
    """运行摘要的原文来源：由 bundle 里的结构化数据重建可核对数字。"""
    meta = run.get("run") or {}
    task = run.get("task") or {}
    candidates = [item for item in (run.get("candidates") or []) if isinstance(item, dict)]
    passed = len([item for item in candidates if item.get("audit_status") == "通过"])
    rejected = len([item for item in candidates if item.get("audit_status") == "否决"])
    delivered = len([item for item in candidates if item.get("delivered")])
    if run.get("delivered_to_user") is not None:
        delivered = int(run.get("delivered_to_user") or 0)
    deliver_count = task.get("deliver_count") if task.get("deliver_count") is not None \
        else run.get("deliver_count")
    lines = [
        f"运行编号：{meta.get('run_no') or meta.get('id') or '未知'}",
        f"运行状态：{meta.get('status') or '未知'}",
        f"调度 {meta.get('total_round', '未知')} 轮",
        f"候选池累计 {len(candidates)} 人",
        f"通过审核 {passed} 人",
        f"否决 {rejected} 人",
        f"交付 {delivered} 人（要求 {deliver_count} 人）"
        if deliver_count is not None else f"交付 {delivered} 人",
    ]
    for stage in (run.get("funnel") or {}).get("stages") or []:
        if isinstance(stage, dict) and stage.get("name"):
            lines.append(f"漏斗节点 {stage.get('name')}：{stage.get('count', '未知')}")
    return "\n".join(lines)


def _item(item_id, kind, role, subject, content, source_text, **extra) -> dict:
    item = {"item_id": item_id, "kind": kind, "role": role,
            "subject_id": (subject or {}).get("id"),
            "subject_nickname": (subject or {}).get("nickname"),
            "content": content, "source_text": source_text,
            "profile": subject or {}}
    item.update(extra)
    return item


def build_items(bundle: dict, limit_items: int = 20, seed: int = SAMPLE_SEED) -> list[dict]:
    """从 bundle 收集内容 item，再按固定种子确定性抽样。

    item 类型：
    - applicant_portrait：申请人画像（summary+标签）
    - candidate_portrait：已交付候选的画像
    - run_summary：运行摘要（模型写的收尾/统计叙述）
    - reject_reason：被否决候选的否决理由（解释文本）
    """
    items: list[dict] = []
    for run_index, run in enumerate(bundle.get("runs") or []):
        if not isinstance(run, dict):
            continue
        key = _run_key(run_index, run)
        applicant = run.get("applicant") or {}
        applicant_source = "\n".join(person_source_lines(applicant))
        portrait = applicant.get("portrait") or {}
        content = portrait_content_text(portrait)
        if content:
            items.append(_item(f"{key}:A", "applicant_portrait", "applicant",
                               applicant, content, applicant_source, run_index=run_index))
        summary = (run.get("run") or {}).get("summary")
        if str(summary or "").strip():
            items.append(_item(f"{key}:S", "run_summary", "run", applicant,
                               str(summary).strip(), run_source_text(run),
                               run_index=run_index))
        for cand_index, candidate in enumerate(run.get("candidates") or []):
            if not isinstance(candidate, dict):
                continue
            cand_key = candidate.get("id") if candidate.get("id") is not None else cand_index
            candidate_source = "\n".join(person_source_lines(candidate))
            portrait = candidate.get("portrait") or {}
            content = portrait_content_text(portrait)
            if candidate.get("delivered") and content:
                items.append(_item(f"{key}:C{cand_key}", "candidate_portrait", "candidate",
                                   candidate, content, candidate_source,
                                   run_index=run_index, candidate_index=cand_index))
            reason = str(candidate.get("reject_reason") or "").strip()
            if candidate.get("audit_status") == "否决" and reason:
                source = "\n".join([
                    "【申请方】" + "\n".join(person_source_lines(applicant)),
                    "【申请方偏好】" + "；".join(
                        preference_source_lines(applicant.get("preference") or {})),
                    "【候选方】" + "\n".join(person_source_lines(candidate)),
                    "【候选方偏好】" + "；".join(
                        preference_source_lines(candidate.get("preference") or {})),
                ])
                items.append(_item(f"{key}:X{cand_key}", "reject_reason", "candidate",
                                   candidate, reason, source,
                                   run_index=run_index, candidate_index=cand_index))
    if limit_items and limit_items > 0 and len(items) > limit_items:
        rng = random.Random(seed)
        rng.shuffle(items)
        items = items[:limit_items]
    return items


def build_judge_materials(items: list[dict]) -> list[dict]:
    """构造发给 judge 的材料：只带 item_id/kind/content/source_text。"""
    materials = []
    for item in items:
        material = {"item_id": item["item_id"], "kind": item["kind"],
                    "content": item["content"], "source_text": item["source_text"]}
        assert_safe_material(material)
        materials.append(material)
    return materials


# ---------------------------------------------------------------------------
# 确定性规则兜底：宠物/吸烟/预算/租期/门店（不调 judge）
# ---------------------------------------------------------------------------
_PET_RE = re.compile(r"(?:养|有)(?:了|着|过)?[^。！？；，,\n]{0,8}(?:猫|狗|宠物|仓鼠|鸟|鱼)")
_PET_NEG_RE = re.compile(r"(?:不养|没养|没有宠物|无宠物|不养宠物|没宠物|从不养)")
_SMOKE_RE = re.compile(r"(?:吸烟|抽烟|烟民)")
_BUDGET_RE = re.compile(r"预算[^0-9]{0,6}(\d{3,6})")
_NEG_PREFIX = ("不", "没", "无", "非", "别", "戒", "从未", "禁止")
# 分句符：只在同一句里找依据，避免把“希望室友不抽烟”当成本人吸烟
_CLAUSE_SPLIT = re.compile(r"[。！？；，,\n]")
# 一句里出现这些词，说明说的是对室友的要求，不是本人
_OTHER_SUBJECT_WORDS = ("室友", "对方", "希望", "接受", "不要", "禁止", "要求")


def _clauses(text: str) -> list[str]:
    return [part for part in _CLAUSE_SPLIT.split(str(text or "")) if part.strip()]


def _pet_positive(text: str) -> bool:
    for clause in _clauses(text):
        if any(word in clause for word in _OTHER_SUBJECT_WORDS):
            continue
        for match in _PET_RE.finditer(clause):
            prefix = clause[max(0, match.start() - 3):match.start()]
            if any(word in prefix for word in _NEG_PREFIX):
                continue
            return True
    return False


def _smoking_state(text: str):
    """画像文本里说的是不是本人吸烟：True=吸烟，False=不吸烟，None=没提。"""
    negative = False
    for clause in _clauses(text):
        for match in _SMOKE_RE.finditer(clause):
            prefix = clause[max(0, match.start() - 6):match.start()]
            if any(word in prefix for word in _NEG_PREFIX):
                negative = True
                continue
            if any(word in clause for word in _OTHER_SUBJECT_WORDS):
                continue
            return True
    return False if negative else None


def _profile_smoking_state(value) -> bool | None:
    text = str(value or "")
    if not text:
        return None
    if "不" in text or "戒" in text or "无" in text:
        return False
    return True


def _budget_mentions(text: str) -> list[int]:
    return [int(match.group(1)) for match in _BUDGET_RE.finditer(text)]


def _lease_mentions(text: str) -> list:
    found = []
    for term in LEASE_TERMS:
        variants = {term, term.replace("-", "到"), term.replace("-", "－")}
        if any(variant in text for variant in variants):
            found.append(term)
    return found


def _store_mentions(text: str) -> list[int]:
    return [store_id for store_id, name in STORE_LIST if name in text]


def _rule_warnings_for(profile: dict, text: str, item_id: str) -> list[dict]:
    warnings = []
    if not text:
        return warnings

    has_pet = str(profile.get("has_pet") or "")
    if has_pet == "无" and _pet_positive(text):
        warnings.append({"item_id": item_id, "dim": "pet",
                         "reason": "画像提到养宠，但档案 has_pet=无"})
    elif has_pet == "有" and not _pet_positive(text) and _PET_NEG_RE.search(text):
        warnings.append({"item_id": item_id, "dim": "pet",
                         "reason": "画像提到不养宠，但档案 has_pet=有"})

    profile_smoke = _profile_smoking_state(profile.get("smoking"))
    text_smoke = _smoking_state(text)
    if profile_smoke is not None and text_smoke is not None and profile_smoke != text_smoke:
        warnings.append({"item_id": item_id, "dim": "smoking",
                         "reason": f"画像吸烟表述与档案 smoking={profile.get('smoking')} 不一致"})

    budget = profile.get("rent_budget")
    if budget is not None:
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            budget = None
    if budget is not None:
        mentioned = _budget_mentions(text)
        wrong = [value for value in mentioned if value != budget]
        if wrong:
            warnings.append({"item_id": item_id, "dim": "budget",
                             "reason": f"画像提到预算 {wrong[0]} 元，与档案预算 {budget} 元不一致"})

    lease = str(profile.get("lease_term") or "").strip()
    if lease:
        mentioned = _lease_mentions(text)
        if mentioned and lease not in mentioned:
            warnings.append({"item_id": item_id, "dim": "lease",
                             "reason": f"画像提到的计划租期（{mentioned[0]}）与档案 {lease} 不一致"})

    store_id = profile.get("store_id")
    if store_id is not None:
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            store_id = None
    if store_id is not None:
        mentioned = _store_mentions(text)
        if mentioned and store_id not in mentioned:
            warnings.append({"item_id": item_id, "dim": "store",
                             "reason": f"画像提到的门店（{STORE_NAMES.get(mentioned[0])}）"
                                       f"与档案意向门店（{STORE_NAMES.get(store_id)}）不一致"})
    return warnings


def rule_warnings(items: list[dict]) -> list[dict]:
    """只对画像类 item 做确定性一致性对账；返回逐条 warning。"""
    warnings = []
    for item in items:
        if not str(item.get("kind") or "").endswith("_portrait"):
            continue
        warnings.extend(_rule_warnings_for(item.get("profile") or {},
                                           str(item.get("content") or ""),
                                           item["item_id"]))
    return warnings


# ---------------------------------------------------------------------------
# judge 调用与输出解析
# ---------------------------------------------------------------------------
LABEL_ALIASES = {
    "supported": "supported", "support": "supported", "supported_by_source": "supported",
    "支持": "supported", "有依据": "supported", "有据": "supported", "符合": "supported",
    "contradicted": "contradicted", "contradiction": "contradicted", "矛盾": "contradicted",
    "冲突": "contradicted", "与原文矛盾": "contradicted", "牴触": "contradicted",
    "not_supported": "not_supported", "notsupported": "not_supported",
    "unsupported": "not_supported", "no_support": "not_supported",
    "无依据": "not_supported", "无支持": "not_supported", "不支持": "not_supported",
    "未支持": "not_supported", "无法核验": "not_supported",
}
COVERED_VALUES = {"covered", "present", "有", "有依据", "是", "true", "齐全", "覆盖"}


def normalize_label(label) -> str:
    text = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    return LABEL_ALIASES.get(text, "not_supported")


def dim_covered(value) -> bool:
    if isinstance(value, bool):
        return value
    return normalize_text(value) in {normalize_text(item) for item in COVERED_VALUES}


def _extract_json(text: str):
    content = re.sub(r"```(?:json)?", "", str(text or "")).strip("` \n")
    match = re.search(r"\{.*\}", content, re.S) or re.search(r"\[.*\]", content, re.S)
    if not match:
        raise ValueError("judge 响应里没有 JSON：" + content[:300])
    return json.loads(match.group(0))


def _outputs_from_payload(payload) -> dict:
    """兼容 {"items":[...]}、{item_id: {...}}、[...] 三种 judge 响应形态。"""
    outputs: dict = {}
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and row.get("item_id") not in (None, ""):
                outputs[str(row["item_id"])] = row
        return outputs
    if not isinstance(payload, dict):
        return outputs
    rows = payload.get("items")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("item_id") not in (None, ""):
                outputs[str(row["item_id"])] = row
        return outputs
    for key, value in payload.items():
        if isinstance(value, dict):
            outputs[str(key)] = dict(value, item_id=str(key))
    return outputs


def _post_judge(prompt: str, env: dict) -> str:
    base_url = str(env.get("EVAL_JUDGE_BASE_URL") or "").rstrip("/")
    api_key = str(env.get("EVAL_JUDGE_API_KEY") or "")
    model = str(env.get("EVAL_JUDGE_MODEL") or "")
    payload = {"model": model, "temperature": 0.0, "max_tokens": JUDGE_MAX_TOKENS,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": prompt}]}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    return (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def _call_judge(materials: list[dict], env: dict) -> dict:
    """真实 judge 调用（OpenAI 兼容 /chat/completions）；测试里整函数替换。

    逐批容错：某一批失败只丢掉这一批，不把整次测量拖成 unusable；缺的条目由
    run() 计入 judge_errors。
    """
    outputs: dict = {}
    for start in range(0, len(materials), JUDGE_BATCH):
        chunk = materials[start:start + JUDGE_BATCH]
        prompt = CONTENT_PROMPT_HEADER + json.dumps(chunk, ensure_ascii=False)
        try:
            payload = _extract_json(_post_judge(prompt, env))
        except Exception:  # noqa: BLE001 - 单批失败不影响其他批
            continue
        outputs.update(_outputs_from_payload(payload))
    return outputs


def _load_fake(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _outputs_from_payload(data)


# 记住“真实调用”的引用：测试/集成注入 judge_fn 或替换 _call_judge 时不再要求 env 配置。
_DEFAULT_CALL_JUDGE = _call_judge


def _require_judge_env(env: dict) -> None:
    missing = [key for key in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")
               if not str((env or {}).get(key) or "").strip()]
    if missing:
        raise SystemExit("缺少 judge 配置：" + "、".join(missing) + "（用 --env-file 指定 .env.eval）")


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def evaluate(items: list[dict], outputs: dict, *, dry_run: bool = False,
             judge_error: str | None = None) -> dict:
    """把 judge 输出与原文校验结果汇总成指标 payload（不含 generated_at）。"""
    claims: list[dict] = []
    by_item: list[dict] = []
    judge_errors = 0
    portrait_items = 0
    portrait_complete = 0

    for item in items:
        item_id = item["item_id"]
        output = outputs.get(item_id)
        raw_claims = []
        required_dims = {}
        if isinstance(output, dict):
            raw_claims = output.get("claims") if isinstance(output.get("claims"), list) else []
            required_dims = output.get("required_dims") if isinstance(output.get("required_dims"), dict) else {}
        elif not dry_run:
            judge_errors += 1
        item_claims = []
        for index, raw in enumerate(raw_claims):
            if not isinstance(raw, dict):
                continue
            claim_text = str(raw.get("claim") or "").strip()
            if not claim_text:
                continue
            label = normalize_label(raw.get("label"))
            quote = str(raw.get("quote") or "").strip()
            verified = quote_in_source(quote, item["source_text"])
            if not verified:
                # quote 找不到原文：不许当 supported/contradicted，降级成 not_supported
                label = "not_supported"
            claim = {
                "claim_id": f"{item_id}-{index + 1}",
                "item_id": item_id,
                "kind": item["kind"],
                "claim": claim_text,
                "label": label,
                "quote": quote,
                "evidence_verified": verified,
                "source_excerpt": source_excerpt(item["source_text"], quote),
            }
            claims.append(claim)
            item_claims.append(claim)
        counts = {label: len([claim for claim in item_claims if claim["label"] == label])
                  for label in LABELS}
        item_verified = len([claim for claim in item_claims if claim["evidence_verified"]])
        is_portrait = str(item["kind"]).endswith("_portrait")
        missing_dims = []
        required_complete = None
        if is_portrait and isinstance(output, dict):
            # 只有 judge 真的给出 required_dims 时才计入覆盖率分母（dry-run 不算 0）
            portrait_items += 1
            covered = [dim for dim in REQUIRED_DIMS if dim_covered(required_dims.get(dim))]
            missing_dims = [dim for dim in REQUIRED_DIMS if dim not in covered]
            required_complete = not missing_dims
            if required_complete:
                portrait_complete += 1
        by_item.append({
            "item_id": item_id,
            "kind": item["kind"],
            "role": item["role"],
            "subject_nickname": item.get("subject_nickname"),
            "n_claims": len(item_claims),
            "supported": counts["supported"],
            "contradicted": counts["contradicted"],
            "not_supported": counts["not_supported"],
            "faithful_rate": round(counts["supported"] / len(item_claims), 4)
            if item_claims else None,
            "evidence_coverage": round(item_verified / len(item_claims), 4)
            if item_claims else None,
            "missing_required_dims": missing_dims,
            "required_dim_complete": required_complete,
            "claims": item_claims,
        })

    n_claims = len(claims)
    supported = len([claim for claim in claims if claim["label"] == "supported"])
    contradicted = len([claim for claim in claims if claim["label"] == "contradicted"])
    not_supported = len([claim for claim in claims if claim["label"] == "not_supported"])
    verified = len([claim for claim in claims if claim["evidence_verified"]])
    faithful_rate = round(supported / n_claims, 4) if n_claims else None
    contradiction_rate = round(contradicted / n_claims, 4) if n_claims else None
    payload = {
        "metric": METRIC,
        "protocol": PROTOCOL,
        "judge_version": JUDGE_VERSION,
        "n_items": len(items),
        "n_claims": n_claims,
        "supported": supported,
        "contradicted": contradicted,
        "not_supported": not_supported,
        "faithful_rate": faithful_rate,
        "faithful_ci95": clopper_pearson_ci(supported, n_claims) if n_claims else None,
        "contradiction_rate": contradiction_rate,
        "contradiction_ci95": clopper_pearson_ci(contradicted, n_claims) if n_claims else None,
        "evidence_coverage": round(verified / n_claims, 4) if n_claims else None,
        "required_dim_coverage": round(portrait_complete / portrait_items, 4)
        if portrait_items else None,
        "by_item": by_item,
        "judge_errors": judge_errors,
    }
    reasons = []
    if dry_run:
        reasons.append("dry-run：未调用 judge，faithful/矛盾率/证据覆盖未测量（规则 warning 仍有效）")
    elif judge_error:
        reasons.append("judge 调用失败：" + str(judge_error)[:200])
    floors = quality_spec.SAMPLE_FLOORS
    if len(items) < floors.get("content_min_items", 50):
        reasons.append(f"item 数 {len(items)} < 设计下限 {floors.get('content_min_items', 50)}")
    if n_claims < floors.get("content_min_claims", 200):
        reasons.append(f"claim 数 {n_claims} < 设计下限 {floors.get('content_min_claims', 200)}")
    if n_claims == 0 and not dry_run and not judge_error:
        reasons.append("judge 没有返回任何 claim")
    usable = (not dry_run) and not judge_error and n_claims > 0
    if items and judge_errors / len(items) > MAX_JUDGE_ERROR_RATE:
        usable = False
        reasons.append(f"judge 失败条目 {judge_errors}/{len(items)} 超过 "
                       f"{int(MAX_JUDGE_ERROR_RATE * 100)}%")
    payload["usable"] = usable
    payload["reasons"] = reasons
    return payload


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def run(bundle: dict, *, env: dict | None = None, judge_fn=None,
        limit_items: int = 20, dry_run: bool = False, fake: dict | None = None,
        seed: int = SAMPLE_SEED) -> dict:
    """构建 item → 调 judge（或 fake/dry-run）→ 汇总指标；返回落盘 payload。"""
    items = build_items(bundle, limit_items=limit_items, seed=seed)
    rules = rule_warnings(items)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outputs: dict = {}
    judge_error = None
    judge_model = str((env or {}).get("EVAL_JUDGE_MODEL") or "") or None
    if dry_run:
        pass
    elif fake is not None:
        outputs = dict(fake)
    elif items:
        env = env or {}
        judge_fn = judge_fn or _call_judge
        if judge_fn is _DEFAULT_CALL_JUDGE:
            _require_judge_env(env)
        try:
            outputs = judge_fn(build_judge_materials(items), env) or {}
        except Exception as exc:  # noqa: BLE001 - judge 失败要落进 artifact，不能吞掉
            outputs = {}
            judge_error = f"{type(exc).__name__}: {exc}"
        if not outputs and items:
            judge_error = judge_error or "judge 未返回任何结论（全部批次失败）"
    payload = evaluate(items, outputs, dry_run=dry_run, judge_error=judge_error)
    payload.update({
        "generated_at": generated_at,
        "rule_warnings": len(rules),
        "rule_warning_items": rules,
        "judge_model": judge_model,
        "dry_run": bool(dry_run),
        "bundle_meta": bundle.get("meta") or {},
    })
    return payload


def write_human_sample(claims: list[dict], path: Path) -> int:
    """导出人工校准 CSV（task-6 固定列）；返回写出的条数。"""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(HUMAN_SAMPLE_COLUMNS))
        writer.writeheader()
        for claim in claims:
            writer.writerow({
                "claim_id": claim.get("claim_id", ""),
                "item_id": claim.get("item_id", ""),
                "claim": claim.get("claim", ""),
                "judge_label": claim.get("label", ""),
                "judge_quote": claim.get("quote", ""),
                "source_excerpt": claim.get("source_excerpt", ""),
            })
    return len(claims)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="内容忠实度（claim 级，E2→E3）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit-items", type=int, default=20)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--dry-run", action="store_true",
                        help="只跑确定性规则，不调用 judge")
    parser.add_argument("--emit-human-sample", type=Path, default=None,
                        help="导出人工校准 CSV（claim_id,item_id,claim,judge_label,"
                             "judge_quote,source_excerpt）")
    parser.add_argument("--fake-json", type=Path, default=None,
                        help="离线 judge 输出（测试/回归用；格式为 {items:[...]} 或 {item_id:{...}}）")
    args = parser.parse_args(argv)
    if args.dry_run and args.fake_json:
        parser.error("--dry-run 与 --fake-json 只能二选一")
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    env = {} if (args.dry_run or args.fake_json) else load_env(args.env_file)
    fake = _load_fake(args.fake_json) if args.fake_json else None
    payload = run(bundle, env=env, limit_items=args.limit_items,
                  dry_run=args.dry_run, fake=fake)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    if args.emit_human_sample:
        claims = [claim for item in payload.get("by_item") or []
                  for claim in item.get("claims") or []]
        write_human_sample(claims, args.emit_human_sample)
    summary = {key: payload.get(key) for key in (
        "metric", "n_items", "n_claims", "faithful_rate", "contradiction_rate",
        "evidence_coverage", "required_dim_coverage", "rule_warnings", "usable")}
    summary["reasons"] = payload.get("reasons")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
