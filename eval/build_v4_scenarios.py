#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v4 评测集（P1 设计稿：40 正向 + 8 负向，确定性可复现）。

相对 v3 的变化：
- 正向从 8 → 40，覆盖 高/中/低 容量层与 20/20 性别目标；
- 每个场景仍是“门店×性别×租期格”，但按容量分层抽样，避免只挑高容量；
- 负向从 2 → 8（4 缺动态 + 4 缺自我介绍）；
- 生成只依赖种子数据与规则，不连数据库、不调模型；标签需人工/judge，本脚本不生成 gold 标签。

用法：
  python eval/build_v4_scenarios.py          # 生成 eval/frozen/v4/scenarios.json
  python eval/build_v4_scenarios.py --check  # 校验结构与覆盖
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import build_v3_scenarios as v3  # noqa: E402
from lib import rules, seed as seedmod  # noqa: E402

VERSION = "v4"
PROTOCOL_VERSION = "v4-2026-11-04"
SEED = 20261104
AS_OF = date(2026, 11, 4)
DELIVER_COUNT = 8
POSITIVE_COUNT = 40
NEGATIVE_COUNT = 8
FROZEN_DIR = EVAL_DIR / "frozen" / "v4"
SCENARIOS_FILE = "scenarios.json"

# 正向配额：高 16 / 中 12 / 低 12
QUOTAS = (("high", 16), ("medium", 12), ("low", 12))
MUST_PLANS = {
    "high": (None,),
    "medium": (("store", "同门店"), ("budget", "同门店")),
    "low": (("budget", "同门店"), ("pet", "同门店")),
}


def _options(spec: dict, pool, prefs) -> list[dict]:
    out = []
    for store_id in sorted({m.store_id for m in pool if m.store_id}):
        for gender in ("男", "女"):
            for lease_term in rules.LEASE_TERMS:
                capacity, unbounded, raw = 0, 0, 0
                raw = len(v3._raw_cell(pool, store_id, gender, lease_term))
                capacity, unbounded = v3._capacity_for(
                    spec, store_id, gender, lease_term, pool, prefs, AS_OF)
                if not v3._tier_match(capacity, spec["tier"]):
                    continue
                out.append({"store_id": store_id, "gender": gender, "lease_term": lease_term,
                            "capacity": capacity, "unbounded": unbounded, "raw_cell": raw})
    return out


def _select(cell_sets: list[list[dict]], counts: list[int], seed_value: int) -> list[dict]:
    """按层配额 + 目标性别数选择；确定性、无重复格子。"""
    targets = ({"男": 8, "女": 8}, {"男": 4, "女": 8}, {"男": 8, "女": 4})
    rng = random.Random(seed_value)
    used: set[tuple] = set()
    selected: list[dict] = []
    for options, count, target in zip(cell_sets, counts, targets):
        bucket = list(options)
        rng.shuffle(bucket)
        picked: list[dict] = []
        for gender, wanted in (("男", target["男"]), ("女", target["女"])):
            for cell in bucket:
                if len(picked) >= count or sum(1 for x in picked if x["gender"] == gender) >= wanted:
                    break
                if cell["gender"] != gender:
                    continue
                key = (cell["store_id"], cell["gender"], cell["lease_term"])
                if key in used:
                    continue
                used.add(key)
                picked.append(cell)
        if len(picked) < count:
            for cell in bucket:
                if len(picked) >= count:
                    break
                key = (cell["store_id"], cell["gender"], cell["lease_term"])
                if key in used:
                    continue
                used.add(key)
                picked.append(cell)
        if len(picked) < count:
            raise RuntimeError(f"v4 场景选择失败：层剩余可选不足（{len(picked)}/{count}）")
        selected.extend(picked)
    return selected


def _positive(spec: dict, cell: dict, seq: int) -> dict:
    applicant, profile, preference, _app_pref, must_codes = v3._make_applicant(
        spec, cell["store_id"], cell["gender"], cell["lease_term"], AS_OF)
    store_name = rules.store_name(cell["store_id"]) or str(cell["store_id"])
    suffix = {"store": "门店必须", "budget": "预算必须", "pet": "养宠必须"}.get(spec.get("extra"), "容量基线")
    return {
        "key": f"V4_{seq:02d}",
        "account": f"TEST_SCENARIO_V4_{seq:02d}",
        "title": f"V4-{seq:02d} {store_name} · {cell['gender']} · {cell['lease_term']} · {suffix}",
        "run": True,
        "deliver_count": DELIVER_COUNT,
        "profile": profile,
        "preference": preference,
        "moments": v3._moments(seq, store_name, profile["schedule_type"], profile["interest_tags"]),
        "expect": {
            "can_run": True, "blocker": None, "requested": DELIVER_COUNT,
            "ex_ante_eligible": cell["capacity"], "ex_ante_unbounded": cell["unbounded"],
            "note": f"容量 {v3._tier_label(spec)}：同范围 {cell['capacity']} 人（不限门店 {cell['unbounded']} 人）；交付要求 8 人",
        },
        "why": (f"门店×性别×租期格；门店范围 {spec['scope']}；"
                f"必须项 {'、'.join(rules.DIM_NAMES[c] for c in must_codes)}；"
                f"容量 {v3._tier_label(spec)}（eligible {cell['capacity']}）"),
        "ex_ante_capacity": {
            "tier": spec["tier"], "tier_label": v3._tier_label(spec),
            "eligible": cell["capacity"], "eligible_unbounded": cell["unbounded"],
            "raw_cell": cell["raw_cell"], "store_scope": spec["scope"],
            "store_id": cell["store_id"], "store": store_name,
            "area": rules.area_of(cell["store_id"]), "gender": cell["gender"],
            "lease_term": cell["lease_term"],
            "must_dimensions": [rules.DIM_NAMES[c] for c in must_codes],
            "must_codes": list(must_codes), "requested": DELIVER_COUNT,
        },
    }


def _negative(pos: dict, seq: int, kind: str) -> dict:
    profile = dict(pos["profile"])
    preference = dict(pos["preference"])
    if kind == "moment":
        moments = []
        blocker, title = "moment", f"V4-{seq:02d} 档案不完整：无租客动态"
        why = "负向 readiness：profile/preference 齐全，moments 为空，readiness 应在 moment 阻断"
    else:
        profile["self_intro"] = ""
        moments = [f"最近在{rules.store_name(pos['ex_ante_capacity']['store_id'])}附近跑步，回来收拾了一下房间。"]
        blocker, title = "intro", f"V4-{seq:02d} 档案不完整：无自我介绍"
        why = "负向 readiness：self_intro 为空；通过 API 建档应在保存阶段被拒"
    return {
        "key": f"V4_{seq:02d}", "account": f"TEST_SCENARIO_V4_{seq:02d}",
        "title": title, "run": False, "deliver_count": DELIVER_COUNT,
        "profile": profile, "preference": preference, "moments": moments,
        "expect": {"can_run": False, "blocker": blocker, "requested": DELIVER_COUNT,
                   "note": why},
        "why": why,
        "ex_ante_capacity": dict(pos["ex_ante_capacity"], tier="negative", tier_label="负向"),
    }


def build(repo_root: Path | str = REPO, seed_value: int = SEED) -> dict:
    data = seedmod.load_seed(Path(repo_root))
    pool = seedmod.approved_candidates(data)
    prefs = data.preferences
    tier_options: dict[str, list[dict]] = {tier: [] for tier, _ in QUOTAS}
    for tier, count in QUOTAS:
        plans = MUST_PLANS[tier]
        for index in range(count):
            extra, scope = (None, "同片区") if tier == "high" else plans[index % len(plans)]
            spec = {"slot": len(tier_options[tier]) + 1, "extra": extra, "scope": scope,
                    "tier": tier, "_pool": pool}
            for cell in _options(spec, pool, prefs):
                cell = dict(cell, spec=spec)
                tier_options[tier].append(cell)
    chosen = _select([tier_options[tier] for tier, _ in QUOTAS],
                     [count for _, count in QUOTAS], seed_value)
    positives = [_positive(cell["spec"], cell, index + 1) for index, cell in enumerate(chosen)]
    negatives = []
    for index in range(4):
        negatives.append(_negative(positives[index], POSITIVE_COUNT + index + 1, "moment"))
    for index in range(4):
        negatives.append(_negative(positives[index + 4], POSITIVE_COUNT + 4 + index + 1, "intro"))
    scenarios = positives + negatives
    stores = [item["profile"]["store_id"] for item in positives]
    genders = [item["profile"]["gender"] for item in positives]
    leases = [item["profile"]["lease_term"] for item in positives]
    tiers = [item["ex_ante_capacity"]["tier"] for item in positives]
    return {
        "version": VERSION, "suite": VERSION, "seed": seed_value,
        "protocol_version": PROTOCOL_VERSION, "as_of": AS_OF.isoformat(),
        "scenario_count": len(scenarios), "positive_count": len(positives),
        "negative_count": len(negatives), "deliver_count": DELIVER_COUNT,
        "grid": {
            "axes": ["store_id", "gender", "lease_term"],
            "tier_quotas": dict(QUOTAS),
            "tier_counts": {tier: tiers.count(tier) for tier in ("high", "medium", "low")},
            "diversity": {"stores": len(set(stores)), "male": genders.count("男"),
                          "female": genders.count("女"), "lease_terms": len(set(leases))},
            "labels": "pending-human/judge（本文件不含 gold 排序标签）",
            "negative_types": {"moment": 4, "intro": 4},
        },
        "scenarios": scenarios,
    }


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def check(data: dict) -> list[str]:
    errors = []
    positives = [item for item in data["scenarios"] if item.get("run")]
    negatives = [item for item in data["scenarios"] if not item.get("run")]
    if data["positive_count"] != POSITIVE_COUNT:
        errors.append(f"正向数 {data['positive_count']} != {POSITIVE_COUNT}")
    if data["negative_count"] != NEGATIVE_COUNT:
        errors.append(f"负向数 {data['negative_count']} != {NEGATIVE_COUNT}")
    if len(positives) != POSITIVE_COUNT or len(negatives) != NEGATIVE_COUNT:
        errors.append("scenario run 标记与计数不一致")
    cells = [(item["profile"]["store_id"], item["profile"]["gender"], item["profile"]["lease_term"])
             for item in positives]
    if len(cells) != len(set(cells)):
        errors.append("正向场景存在重复格子")
    for item in positives:
        if item["ex_ante_capacity"]["eligible"] < 1:
            errors.append(f"{item['key']} 容量为 0")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 v4 评测集（P1 设计稿）")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    data = build()
    out_dir = args.out or FROZEN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SCENARIOS_FILE
    text = dump(data)
    path.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    errors = check(data)
    if errors:
        print("FAIL:", errors)
        return 1
    print(f"写入 {path} sha256={sha}")
    print(json.dumps(data["grid"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
