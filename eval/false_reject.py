#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审核误拒率（假否决率）与假通过率：硬规则确定性 replay + 软冲突 judge 三分类。

CLI：
  python3 eval/false_reject.py --bundle B.json --out out.json \
      [--limit 100] [--env-file .env.eval] [--dry-run] \
      [--emit-human-sample soft.csv] [--fake-json fake.json]

口径（与 eval/quality_spec.py 的 false_reject 指标对齐）：

* 硬规则部分（E0，确定性）：对所有 reject_code=MISMATCH_HARD 的否决做全量 replay，
  用 eval/lib/rules.py 重算「同性 + 双向必须项 + 租期档差」。代码算不出硬违规但
  审核官仍按硬冲突否决 → hard false reject。同一次 replay 也检查所有「通过」候选：
  存在硬违规却通过 → false_pass（漏放必须项，必须为 0）。
* 软冲突部分（E2，judge）：只评 reject_code=PREFERENCE_CONFLICT/PORTRAIT_INSUFFICIENT
  的否决，judge 三分类：合理拒绝 / 应通过 / 需补资料；「应通过」计入软误拒率。
  软冲突样本按 --limit 做确定性抽样（控制 judge 成本），可导出人工校准 CSV。
* 没有 reject_code 或未知 code 的否决单独统计，不计入 hard.rate（不能把软否决
  误算成硬误拒）；软冲突否决里如果 replay 出硬违规，单独记为分类不一致。
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from lib.env import load_env  # noqa: E402
from lib.rules import STORE_NAMES, area_of, bidirectional_violations  # noqa: E402
from lib.seed import member_from_payload, preference_from_payload  # noqa: E402
from lib.stats import clopper_pearson_ci  # noqa: E402
import quality_spec  # noqa: E402

METRIC = "false_reject"
PROTOCOL = quality_spec.PROTOCOL_VERSION
JUDGE_VERSION = quality_spec.JUDGE_VERSION
DEFAULT_ENV = EVAL_DIR.parent / ".env.eval"

SAMPLE_SEED = 20261106
JUDGE_BATCH = 4
JUDGE_TIMEOUT = 120
MAX_JUDGE_ERROR_RATE = 0.2

AUDIT_PASS = "通过"
AUDIT_REJECT = "否决"
HARD_CODES = ("MISMATCH_HARD",)
SOFT_CODES = ("PREFERENCE_CONFLICT", "PORTRAIT_INSUFFICIENT")
UNCODED = "UNCODED"

SOFT_LABELS = ("reasonable_reject", "should_pass", "needs_info")
SOFT_LABEL_ALIASES = {
    "reasonable_reject": "reasonable_reject", "reasonable": "reasonable_reject",
    "合理拒绝": "reasonable_reject", "拒绝合理": "reasonable_reject",
    "should_pass": "should_pass", "shouldpass": "should_pass", "pass": "should_pass",
    "应通过": "should_pass", "该通过": "should_pass", "误拒": "should_pass",
    "needs_info": "needs_info", "needs_more_info": "needs_info", "need_info": "needs_info",
    "需补资料": "needs_info", "需要补资料": "needs_info", "补充资料": "needs_info",
    "信息不足": "needs_info",
}
# 不能出现在发给 judge 的材料里的系统元数据字段（self_check 也扫这一组；
# reject_code/reject_reason 是被评对象本身，属于允许字段）
FORBIDDEN_MATERIAL_KEYS = frozenset({
    "delivered", "delivered_rank", "screen_score", "evidence", "passed",
    "truncated", "candidate_row_id", "found_round", "relax_note", "audit_round",
    "rank", "deliverable_passed_count", "delivered_to_user", "truncated_count",
})
HUMAN_SAMPLE_COLUMNS = ("item_id", "scenario", "reject_code", "reject_reason",
                        "judge_label", "judge_reason",
                        "applicant_nickname", "candidate_nickname")

SOFT_PROMPT_HEADER = """你是合租匹配审核的独立复核员。下面每条 item 是「审核官否决了一位候选」的记录：
- reject_code/reject_reason：审核官给出的否决分类与理由（被复核对象）；
- applicant/applicant_preference：申请方档案与合住偏好；
- candidate/candidate_preference：候选方档案与合住偏好。

请判断这次否决是否应该成立，三分类（只输出英文枚举）：
- reasonable_reject：否决合理（申请方确实不满足候选方的必须项，或双方存在明确冲突）；
- should_pass：否决不合理，按资料看应该通过（误拒）；
- needs_info：资料不足以判断，需要申请人补充资料后再匹配（不算误拒）。
注意：硬规则（同性/双方标为必须的条件/租期档差）不由你重判；这里只评估软冲突
（作息、整洁、吸烟等习惯冲突）与画像不足。理由只写一句话。

只输出一个 JSON 对象：
{"items":[{"item_id":"...","label":"reasonable_reject|should_pass|needs_info","reason":"一句话"}]}
不要 markdown、不要解释、不要输出 JSON 以外的东西。

材料：
"""


# ---------------------------------------------------------------------------
# 材料白名单（judge 只该看用户内容与受审的否决记录）
# ---------------------------------------------------------------------------
def _walk_keys(node) -> list:
    keys = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_walk_keys(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            keys.extend(_walk_keys(value))
    return keys


def assert_safe_material(material) -> None:
    """材料里出现系统元数据字段就报错；reject_code/reject_reason 是允许的被评对象。"""
    keys = set(_walk_keys(material))
    forbidden = sorted((FORBIDDEN_MATERIAL_KEYS | {"audit_status"}) & keys)
    if forbidden:
        raise ValueError("judge 材料含系统元数据字段：" + "、".join(forbidden))


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _tags_text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (list, tuple, set)):
        return "，".join(str(item).strip() for item in value if str(item).strip())
    return str(value)


def _portrait_text(portrait: dict) -> str:
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


def safe_person(profile: dict) -> dict:
    """只带用户内容（档案字段 + 画像 + 动态），不带任何系统元数据。"""
    profile = profile or {}
    store_id = profile.get("store_id")
    store_text = ""
    if store_id is not None:
        name = profile.get("store_name") or STORE_NAMES.get(store_id) or ""
        area = profile.get("store_area") or area_of(store_id) or ""
        store_text = name + (f"（{area}片区）" if area else "")
    moments = []
    for moment in profile.get("moments") or []:
        content = (moment or {}).get("content") if isinstance(moment, dict) else moment
        if str(content or "").strip():
            moments.append(str(content).strip())
    return {
        "nickname": profile.get("nickname"),
        "gender": profile.get("gender"),
        "birth_date": profile.get("birth_date"),
        "rent_budget": profile.get("rent_budget"),
        "tidiness": profile.get("tidiness"),
        "occupation": profile.get("occupation"),
        "lease_term": profile.get("lease_term"),
        "store": store_text,
        "schedule_type": profile.get("schedule_type"),
        "has_pet": profile.get("has_pet"),
        "smoking": profile.get("smoking"),
        "self_intro": profile.get("self_intro"),
        "roommate_expectation": profile.get("roommate_expectation"),
        "interest_tags": _tags_text(profile.get("interest_tags")),
        "portrait": _portrait_text(profile.get("portrait") or {}),
        "moments": moments,
    }


def _clean_preference_payload(payload) -> dict:
    """把 bundle 里「字符串化」的偏好还原成可解析的字典（'None' 视为空）。"""
    data = dict(payload or {})
    for key, value in list(data.items()):
        if isinstance(value, str) and value.strip() in ("None", "null", "NULL", ""):
            data[key] = None
        elif isinstance(value, str) and value.strip() == "不限" and key in (
                "age_min", "age_max", "budget_min", "budget_max",
                "tidiness_min", "lease_min", "pet_accept", "store_scope"):
            data[key] = None if key not in ("pet_accept", "store_scope") else value
    return data


def preference_text(payload) -> str:
    """把偏好摊成中文行（judge 材料 / 人工校准都用同一份可读口径）。"""
    data = _clean_preference_payload(payload)

    def has(key):
        return data.get(key) not in (None, "")

    lines = []
    if has("age_min") or has("age_max"):
        lines.append(f"年龄 {data.get('age_min') or '不限'}-{data.get('age_max') or '不限'} 岁"
                     f"（{_plain(data.get('age_required'))}）")
    if has("budget_min") or has("budget_max"):
        lines.append(f"预算 {data.get('budget_min') or '不限'}-{data.get('budget_max') or '不限'} 元"
                     f"（{_plain(data.get('budget_required'))}）")
    if has("tidiness_min"):
        lines.append(f"整洁度不低于 {data.get('tidiness_min')}"
                     f"（{_plain(data.get('tidiness_required'))}）")
    if has("store_scope"):
        lines.append(f"门店 {data.get('store_scope')}（{_plain(data.get('store_required'))}）")
    schedule = _tags_text(data.get("schedule_accept"))
    if schedule:
        lines.append(f"可接受作息 {schedule}（{_plain(data.get('schedule_required'))}）")
    if has("lease_min"):
        lines.append(f"租期不低于 {data.get('lease_min')}"
                     f"（{_plain(data.get('lease_required'))}）")
    if has("pet_accept"):
        lines.append(f"宠物态度 {data.get('pet_accept')}"
                     f"（{_plain(data.get('pet_required'))}）")
    return "；".join(lines) or "未填写合住偏好"


# ---------------------------------------------------------------------------
# 硬规则 replay（E0，确定性全量）
# ---------------------------------------------------------------------------
def _member(payload):
    return member_from_payload(payload or {}, member_id=int((payload or {}).get("id") or 0))


def _preference(payload):
    cleaned = _clean_preference_payload((payload or {}).get("preference") or {})
    return preference_from_payload(cleaned, member_id=int((payload or {}).get("id") or 0))


def _scenario_name(run_index: int, run: dict) -> str:
    meta = run.get("run") or {}
    applicant = run.get("applicant") or {}
    for value in (applicant.get("username"), meta.get("run_no"), meta.get("id")):
        if value not in (None, ""):
            return str(value)
    return f"run{run_index}"


def bundle_as_of(bundle: dict):
    """从 bundle 的生成时间取固定 as_of（年龄现算要可复现）；取不到返回 None。"""
    candidates = [(bundle.get("meta") or {}).get("generated_at"), bundle.get("generated_at")]
    for value in candidates:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def replay(bundle: dict, as_of=None) -> dict:
    """用 lib.rules 重算每位已审候选的双向硬规则；返回 rejected / passed 明细。"""
    as_of_date = as_of if as_of is not None else bundle_as_of(bundle)
    rejected: list[dict] = []
    passed: list[dict] = []
    runs = bundle.get("runs") or []
    for run_index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        applicant_payload = run.get("applicant") or {}
        applicant = _member(applicant_payload)
        applicant_preference = _preference(applicant_payload)
        scenario = _scenario_name(run_index, run)
        for candidate_index, candidate_payload in enumerate(run.get("candidates") or []):
            if not isinstance(candidate_payload, dict):
                continue
            candidate = _member(candidate_payload)
            candidate_preference = _preference(candidate_payload)
            violations = bidirectional_violations(
                applicant, applicant_preference, candidate, candidate_preference,
                as_of=as_of_date)
            status = str(candidate_payload.get("audit_status") or "").strip()
            candidate_id = candidate_payload.get("id")
            row = {
                "run_index": run_index,
                "candidate_index": candidate_index,
                "scenario": scenario,
                "run_id": (run.get("run") or {}).get("id"),
                "candidate_id": candidate_id,
                "nickname": candidate_payload.get("nickname"),
                "delivered": bool(candidate_payload.get("delivered")),
                "violations": violations,
                "hard_violation": bool(violations),
                "applicant": applicant_payload,
                "candidate": candidate_payload,
            }
            if status == AUDIT_REJECT:
                code = str(candidate_payload.get("reject_code") or "").strip() or UNCODED
                row.update({
                    "item_id": f"{scenario}:R{candidate_id if candidate_id is not None else candidate_index}",
                    "code": code,
                    "reason": str(candidate_payload.get("reject_reason") or "").strip(),
                })
                rejected.append(row)
            elif status == AUDIT_PASS:
                row.update({"item_id": f"{scenario}:P{candidate_id if candidate_id is not None else candidate_index}"})
                passed.append(row)
    return {"rejected": rejected, "passed": passed,
            "as_of": as_of_date.isoformat() if as_of_date else None,
            "runs": len([run for run in runs if isinstance(run, dict)])}


# ---------------------------------------------------------------------------
# 软冲突材料 / judge
# ---------------------------------------------------------------------------
def sample_rows(rows: list[dict], limit: int, seed: int = SAMPLE_SEED) -> list[dict]:
    """确定性抽样（同一 bundle+limit 每次抽到同一批 item_id）。"""
    rows = list(rows)
    if limit and limit > 0 and len(rows) > limit:
        random.Random(seed).shuffle(rows)
        rows = rows[:limit]
    return rows


def build_judge_materials(rows: list[dict]) -> list[dict]:
    """软冲突 judge 材料：受审的否决记录 + 双方档案/偏好（不含系统元数据）。"""
    materials = []
    for row in rows:
        material = {
            "item_id": row["item_id"],
            "kind": "soft_reject",
            "reject_code": row["code"],
            "reject_reason": row["reason"],
            "applicant": safe_person(row["applicant"]),
            "applicant_preference": preference_text(row["applicant"].get("preference") or {}),
            "candidate": safe_person(row["candidate"]),
            "candidate_preference": preference_text(row["candidate"].get("preference") or {}),
        }
        assert_safe_material(material)
        materials.append(material)
    return materials


SOFT_LABEL_KEYS = ("label", "verdict", "judgement")
SOFT_REASON_KEYS = ("reason", "why", "explanation")


def normalize_soft_label(value) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return SOFT_LABEL_ALIASES.get(text)


def _extract_json(text: str):
    content = re.sub(r"```(?:json)?", "", str(text or "")).strip("` \n")
    match = re.search(r"\{.*\}", content, re.S) or re.search(r"\[.*\]", content, re.S)
    if not match:
        raise ValueError("judge 响应里没有 JSON：" + content[:300])
    return json.loads(match.group(0))


def _outputs_from_payload(payload) -> dict:
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
    payload = {"model": model, "temperature": 0.0, "max_tokens": 2048,
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

    逐批容错：某一批失败只丢掉这一批；缺的条目由 run() 计入 judge_errors。
    """
    outputs: dict = {}
    for start in range(0, len(materials), JUDGE_BATCH):
        chunk = materials[start:start + JUDGE_BATCH]
        prompt = SOFT_PROMPT_HEADER + json.dumps(chunk, ensure_ascii=False)
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
# 指标汇总
# ---------------------------------------------------------------------------
def _rate(count: int, total: int, label: str = "rate") -> dict:
    return {label: round(count / total, 4) if total else None,
            "ci95": clopper_pearson_ci(count, total) if total else None}


def _scenario_bucket(rows: dict, name: str) -> dict:
    if name not in rows:
        rows[name] = {"scenario": name, "rejects": 0, "hard_rejects": 0,
                      "hard_false_reject": 0, "soft_judged": 0, "soft_should_pass": 0,
                      "passed": 0, "false_pass": 0}
    return rows[name]


def evaluate(replay_result: dict, outputs: dict, *, limit: int = 100,
             dry_run: bool = False, judge_error: str | None = None) -> dict:
    """把 replay 结果与软冲突 judge 输出汇总成指标 payload（不含 generated_at）。"""
    rejected = replay_result["rejected"]
    passed = replay_result["passed"]
    hard_rows = [row for row in rejected if row["code"] in HARD_CODES]
    soft_rows = [row for row in rejected if row["code"] in SOFT_CODES]
    other_rows = [row for row in rejected
                  if row["code"] not in HARD_CODES and row["code"] not in SOFT_CODES]
    soft_mismatch = [row for row in soft_rows if row["hard_violation"]]
    hard_false = [row for row in hard_rows if not row["hard_violation"]]

    hard_by_code: dict = {}
    for row in hard_rows:
        bucket = hard_by_code.setdefault(row["code"], {"n": 0, "false_reject": 0})
        bucket["n"] += 1
        if not row["hard_violation"]:
            bucket["false_reject"] += 1
    for code, bucket in hard_by_code.items():
        bucket.update(_rate(bucket["false_reject"], bucket["n"]))
    hard_rate = _rate(len(hard_false), len(hard_rows))
    hard = {"n": len(hard_rows), "false_reject": len(hard_false),
            "rate": hard_rate["rate"], "ci95": hard_rate["ci95"],
            "by_code": hard_by_code}

    # 软冲突：确定性抽样后调 judge（dry-run 不调）
    sampled = sample_rows(soft_rows, limit)
    soft_items = []
    errors = 0
    judged_rows = []
    if not dry_run and sampled:
        judge_outputs = outputs or {}
        for row in sampled:
            raw = judge_outputs.get(row["item_id"])
            nickname = {
                "applicant_nickname": (row["applicant"] or {}).get("nickname"),
                "candidate_nickname": (row["candidate"] or {}).get("nickname"),
            }
            label = None
            reason = ""
            if isinstance(raw, dict):
                for key in SOFT_LABEL_KEYS:
                    label = normalize_soft_label(raw.get(key))
                    if label:
                        break
                for key in SOFT_REASON_KEYS:
                    if raw.get(key):
                        reason = str(raw.get(key))
                        break
            if label is None:
                errors += 1
                soft_items.append({"item_id": row["item_id"], "scenario": row["scenario"],
                                   "candidate_id": row["candidate_id"], "code": row["code"],
                                   "label": None, "reason": reason,
                                   "reject_reason": row["reason"], **nickname})
                continue
            judged_rows.append(row)
            soft_items.append({"item_id": row["item_id"], "scenario": row["scenario"],
                               "candidate_id": row["candidate_id"], "code": row["code"],
                               "label": label, "reason": reason,
                               "reject_reason": row["reason"], **nickname})
    should_pass = len([item for item in soft_items if item["label"] == "should_pass"])
    needs_info = len([item for item in soft_items if item["label"] == "needs_info"])
    reasonable = len([item for item in soft_items if item["label"] == "reasonable_reject"])
    soft_n = len(judged_rows)
    soft_rate = _rate(should_pass, soft_n)
    soft = {"n": soft_n, "sampled": len(sampled), "false_reject": should_pass,
            "should_pass": should_pass, "needs_info": needs_info,
            "reasonable_reject": reasonable, "errors": errors,
            "rate": soft_rate["rate"], "ci95": soft_rate["ci95"],
            "limit": limit, "items": soft_items}

    # 假通过：所有通过候选全量 replay，发现硬违规即漏放
    false_pass_rows = [row for row in passed if row["hard_violation"]]
    false_pass_rate = _rate(len(false_pass_rows), len(passed))
    false_pass = {"n": len(passed), "count": len(false_pass_rows),
                  "rate": false_pass_rate["rate"], "ci95": false_pass_rate["ci95"],
                  "items": [{"scenario": row["scenario"], "candidate_id": row["candidate_id"],
                             "nickname": row["nickname"], "violations": row["violations"]}
                            for row in false_pass_rows]}

    # by_scenario：否决/误拒/假通过逐场景归因
    buckets: dict = {}
    for row in rejected:
        bucket = _scenario_bucket(buckets, row["scenario"])
        bucket["rejects"] += 1
        if row["code"] in HARD_CODES:
            bucket["hard_rejects"] += 1
            if not row["hard_violation"]:
                bucket["hard_false_reject"] += 1
    for item in soft_items:
        if item["label"] is None:
            continue
        bucket = _scenario_bucket(buckets, item["scenario"])
        bucket["soft_judged"] += 1
        if item["label"] == "should_pass":
            bucket["soft_should_pass"] += 1
    for row in passed:
        bucket = _scenario_bucket(buckets, row["scenario"])
        bucket["passed"] += 1
        if row["hard_violation"]:
            bucket["false_pass"] += 1
    by_scenario = [buckets[key] for key in sorted(buckets)]

    reject_code_counts: dict = {}
    for row in rejected:
        reject_code_counts[row["code"]] = reject_code_counts.get(row["code"], 0) + 1

    reasons = []
    if dry_run:
        reasons.append("dry-run：软冲突未评（hard/false_pass 为确定性全量 replay，可直接使用）")
    if judge_error:
        reasons.append("judge 调用失败：" + str(judge_error)[:200])
    if other_rows:
        reasons.append(f"{len(other_rows)} 条否决没有 reject_code/未知 code，未计入 hard.rate")
    if soft_mismatch:
        reasons.append(f"{len(soft_mismatch)} 条软冲突否决 replay 出硬规则违规，"
                       "reject_code 可能分类错误")
    if soft_rows and not dry_run and sampled:
        if not soft_n:
            reasons.append("软冲突没有任何有效 judge 标签")
        elif errors / len(sampled) > MAX_JUDGE_ERROR_RATE:
            reasons.append(f"judge 失败条目 {errors}/{len(sampled)} 超过 "
                           f"{int(MAX_JUDGE_ERROR_RATE * 100)}%")
    floors = quality_spec.SAMPLE_FLOORS
    if len(rejected) < floors.get("false_reject_min_rejects", 100):
        reasons.append(f"否决数 {len(rejected)} < 设计下限 "
                       f"{floors.get('false_reject_min_rejects', 100)}")
    if soft_n < floors.get("false_reject_min_soft", 50):
        reasons.append(f"软冲突有效样本 {soft_n} < 设计下限 "
                       f"{floors.get('false_reject_min_soft', 50)}")

    usable = True
    if not rejected and not passed:
        usable = False
        reasons.append("bundle 里没有已审候选（audit_status=通过/否决）")
    if judge_error:
        usable = False
    if dry_run and soft_rows:
        usable = False
    if sampled and not dry_run:
        if not soft_n:
            usable = False
        elif errors / len(sampled) > MAX_JUDGE_ERROR_RATE:
            usable = False

    return {
        "metric": METRIC,
        "protocol": PROTOCOL,
        "judge_version": JUDGE_VERSION,
        "hard": hard,
        "soft": soft,
        "false_pass": false_pass,
        "by_scenario": by_scenario,
        "reject_code_counts": reject_code_counts,
        "code_mismatch": {"soft_with_hard_violation": len(soft_mismatch)},
        "totals": {"runs": replay_result.get("runs", 0),
                   "rejected": len(rejected), "passed": len(passed),
                   "hard_replay": len(hard_rows), "soft_replay": len(soft_rows),
                   "other_rejected": len(other_rows)},
        "as_of": replay_result.get("as_of"),
        "usable": usable,
        "reasons": reasons,
        "judge_errors": errors,
        "dry_run": bool(dry_run),
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def run(bundle: dict, *, env: dict | None = None, judge_fn=None, limit: int = 100,
        dry_run: bool = False, fake: dict | None = None, as_of=None) -> dict:
    """replay 硬规则 → 软冲突 judge（或 fake/dry-run）→ 汇总指标；返回落盘 payload。"""
    replay_result = replay(bundle, as_of=as_of)
    outputs: dict = {}
    judge_error = None
    soft_rows = [row for row in replay_result["rejected"] if row["code"] in SOFT_CODES]
    if dry_run:
        pass
    elif fake is not None:
        outputs = dict(fake)
    elif soft_rows:
        env = env or {}
        judge_fn = judge_fn or _call_judge
        if judge_fn is _DEFAULT_CALL_JUDGE:
            _require_judge_env(env)
        sampled = sample_rows(soft_rows, limit)
        try:
            outputs = judge_fn(build_judge_materials(sampled), env) or {}
        except Exception as exc:  # noqa: BLE001 - judge 失败要落进 artifact
            outputs = {}
            judge_error = f"{type(exc).__name__}: {exc}"
        if not outputs and sampled:
            judge_error = judge_error or "judge 未返回任何结论（全部批次失败）"
    payload = evaluate(replay_result, outputs, limit=limit,
                       dry_run=dry_run, judge_error=judge_error)
    payload.update({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "judge_model": str((env or {}).get("EVAL_JUDGE_MODEL") or "") or None,
        "bundle_meta": bundle.get("meta") or {},
    })
    return payload


def write_human_sample(items: list[dict], path: Path) -> int:
    """导出软冲突人工校准 CSV；返回写出的条数。"""
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(HUMAN_SAMPLE_COLUMNS))
        writer.writeheader()
        for item in items:
            writer.writerow({
                "item_id": item.get("item_id"),
                "scenario": item.get("scenario"),
                "reject_code": item.get("code"),
                "reject_reason": item.get("reject_reason"),
                "judge_label": item.get("label") or "",
                "judge_reason": item.get("reason") or "",
                "applicant_nickname": item.get("applicant_nickname") or "",
                "candidate_nickname": item.get("candidate_nickname") or "",
            })
    return len(items)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="审核误拒率 / 假通过率（E0+E2）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=100,
                        help="软冲突 judge 确定性抽样上限（硬规则与假通过不受此限）")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--dry-run", action="store_true",
                        help="只跑硬规则 replay + 假通过检测，不调用 judge")
    parser.add_argument("--emit-human-sample", type=Path, default=None,
                        help="导出软冲突人工校准 CSV")
    parser.add_argument("--fake-json", type=Path, default=None,
                        help="离线 judge 输出（测试/回归用；{items:[...]} 或 {item_id:{...}}）")
    args = parser.parse_args(argv)
    if args.dry_run and args.fake_json:
        parser.error("--dry-run 与 --fake-json 只能二选一")
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    env = {} if (args.dry_run or args.fake_json) else load_env(args.env_file)
    fake = _load_fake(args.fake_json) if args.fake_json else None
    payload = run(bundle, env=env, limit=args.limit,
                  dry_run=args.dry_run, fake=fake)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    if args.emit_human_sample:
        write_human_sample(payload.get("soft", {}).get("items") or [],
                           args.emit_human_sample)
    summary = {key: payload.get(key) for key in (
        "metric", "hard", "soft", "false_pass", "usable")}
    summary["soft"] = {key: value for key, value in (payload.get("soft") or {}).items()
                       if key != "items"}
    summary["reasons"] = payload.get("reasons")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
