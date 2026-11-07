#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v4 评测集（40 正向 + 8 负向，确定性可复现；2026-11-05 重冻）。

相对 2026-11-04 版（审计 A4 结论）的修复：

1. 选项阶段只用一个占位 slot（=1）算容量；选中后按最终顺序赋 slot=seq（1..40），
   再用 seq 重新生成档案。旧版把“该层已收集的选项数 + 1”当 slot，会生成
   “我第 208 次来这座城市工作”和重复的“V3场景租客208”昵称。
2. 档案改为“先清洗兴趣标签、再生成 self_intro/moments”：has_pet=无 时删掉
   养猫/撸猫等养宠类标签并用中性标签补齐，再用清洗后的标签重建文本，消除
   “不养宠物…最近常做的事是养猫、撸猫”这类自相矛盾。
3. 负向 8 个固定从正向索引 [0,5,10,15,20,25,30,35] 派生（moment/intro 各 4），
   两种负向都跨容量层、跨性别（旧版只是复制前 8 个正向，全是高容量层）。
4. 每个正向加 expect.target=min(8, eligible_unbounded) 与 target_rule，
   供 pass^k / target attainment 使用（口径：门店为加分项时 scoped 容量不是上限）。
5. --write（默认）写 scenarios.json、MANIFEST.json、COVERAGE.md；
   --check 只读校验，失败退出码 1，不写任何文件。

安全性：只读 deploy/mysql/sql/base 的种子 SQL（经 eval/lib/seed.py），
不连数据库、不调模型；MANIFEST 的 base SQL 指纹 / 候选池指纹由
eval/lib/freeze.py 计算，supply_additions 由扫描 eval profile SQL 得出（必须 0）。

用法：
  python3 eval/build_v4_scenarios.py            # 重新生成并冻结（默认写）
  python3 eval/build_v4_scenarios.py --check    # 只读校验当前冻结
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
for _path in (str(EVAL_DIR), str(REPO)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_v3_scenarios as v3  # noqa: E402
from lib import freeze, rules, seed as seedmod  # noqa: E402

HUMAN_EVAL_DIR = EVAL_DIR / "human_eval"
if str(HUMAN_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(HUMAN_EVAL_DIR))
from data_consistency import assess_person  # noqa: E402

VERSION = "v4"
PROTOCOL_VERSION = "v4-2026-11-06b"
SEED = 20261104
AS_OF = date(2026, 11, 4)
DELIVER_COUNT = 8
POSITIVE_COUNT = 40
NEGATIVE_COUNT = 8
FROZEN_DIR = EVAL_DIR / "frozen" / "v4"
SCENARIOS_FILE = "scenarios.json"
MANIFEST_FILE = "MANIFEST.json"
COVERAGE_FILE = "COVERAGE.md"
LABELS_FILE = "labels.json"
TARGET_RULE = "min(8, eligible_unbounded)"
LABELS_METHOD = "human/judge 0-3"

# 正向配额：高 16 / 中 12 / 低 12（与 v4 设计稿一致）
QUOTAS = (("high", 16), ("medium", 12), ("low", 12))
MUST_PLANS = {
    "high": (None,),
    "medium": (("store", "同门店"), ("budget", "同门店")),
    "low": (("budget", "同门店"), ("pet", "同门店")),
}
# 每层的性别目标（旧版实际 19/21：中容量层受格子容量与全局去重约束，男 4 不可达）
TIER_TARGETS = ({"男": 8, "女": 8}, {"男": 4, "女": 8}, {"男": 8, "女": 4})

# 负向固定从这些正向索引派生（跨层：高 0/5/10/15、中 20/25、低 30/35）
NEGATIVE_SOURCE_INDICES = (0, 5, 10, 15, 20, 25, 30, 35)
NEGATIVE_PARTITION_SIZE = 4

# v4 数据质量：生成档案后去掉“无宠物/不接受宠物”档案里的养宠类兴趣标签，
# 避免 v3 面板发现的“兴趣含养猫 vs has_pet=无/过敏”自相矛盾。
PET_TAGS = ("养猫", "撸猫", "养狗", "遛狗", "养仓鼠", "仓鼠", "爬宠", "爬行动物",
            "养鱼", "水族", "宠物摄影", "猫咖", "狗咖")
FALLBACK_TAGS = ("看电影", "听音乐", "跑步", "咖啡", "看展", "爬山", "小说", "桌游")
# 自由文本里出现这些词说明“在养/在撸宠物”；与“不养宠物/过敏”同现即矛盾。
PET_TEXT_WORDS = PET_TAGS
NO_PET_PHRASES = ("不养宠物", "不能接受宠物", "不接受宠物", "对动物毛发过敏",
                  "动物毛发过敏", "不能接受室友养宠", "不太能接受室友养宠",
                  "不能接受室友养宠物", "过敏")

_TABLE_CACHE: dict[tuple, list[dict]] = {}


# ---------------------------------------------------------------- 计划与容量
def _plan_list() -> list[dict]:
    """最终 40 个正向场景的“建造计划”（顺序即 slot=seq 的顺序）。"""
    plans: list[dict] = []
    for tier, count in QUOTAS:
        tier_plans = MUST_PLANS[tier]
        for index in range(count):
            if tier == "high":
                extra, scope = None, "同片区"
            else:
                extra, scope = tier_plans[index % len(tier_plans)]
            plans.append({"tier": tier, "extra": extra, "scope": scope})
    return plans


def _capacity_table(extra: str | None, scope: str, pool, prefs,
                    repo_key: str, seed_value: int) -> list[dict]:
    """一个（extra, scope）规格下全部（门店×性别×租期）格子的容量表。

    容量与 slot 的奇偶有关：v3._make_applicant 的 tidiness（整洁/一般）与
    schedule_accept（偶数 slot 多接受“正常作息”）都按 slot 奇偶变化。因此选项
    阶段同时算 slot=1（奇数位）与 slot=2（偶数位）两套容量，选中后再按最终
    seq 的奇偶取对应值，保证 expect.ex_ante_eligible 与最终档案一致。
    """
    cache_key = (repo_key, AS_OF.isoformat(), seed_value, str(extra), scope)
    if cache_key in _TABLE_CACHE:
        return _TABLE_CACHE[cache_key]
    cells: list[dict] = []
    for store_id in sorted({member.store_id for member in pool if member.store_id}):
        for gender in ("男", "女"):
            for lease_term in rules.LEASE_TERMS:
                capacities: dict[int, tuple[int, int]] = {}
                for parity_slot in (1, 2):
                    spec = {"slot": parity_slot, "extra": extra, "scope": scope,
                            "tier": "high", "_pool": pool}
                    capacities[parity_slot] = v3._capacity_for(
                        spec, store_id, gender, lease_term, pool, prefs, AS_OF)
                cells.append({
                    "store_id": store_id,
                    "gender": gender,
                    "lease_term": lease_term,
                    "capacity": {1: capacities[1][0], 2: capacities[2][0]},
                    "unbounded": {1: capacities[1][1], 2: capacities[2][1]},
                    "raw_cell": len(v3._raw_cell(pool, store_id, gender, lease_term)),
                })
    _TABLE_CACHE[cache_key] = cells
    return cells


def _cell_key(cell: dict) -> tuple:
    return (cell["store_id"], cell["gender"], cell["lease_term"])


# 选择顺序：先挑“可用格子最少”的中容量层。中容量格子在奇偶容量与全局去重下
# 最紧张（budget/同门店 规格只有个位数格子能落在中容量区间），若先挑高容量层会
# 吃掉这些格子导致无解；先选中容量层后三层都能满足性别目标（20 男 / 20 女）。
SELECTION_TIER_ORDER = ("medium", "high", "low")


def _select(plans: list[dict], tables: dict[tuple, list[dict]],
            seed_value: int) -> list[dict]:
    """确定性选择 40 个无重复格子，并保证每个位置 seq 按最终奇偶满足容量层。

    每个位置必须与计划槽位（含 final seq 奇偶）的容量层匹配，并被全局去重；
    层内先按性别目标挑（男目标数优先、再女），不足时用任意性别补齐。
    返回的 cells 与 plans 一一对应。
    """
    rng = random.Random(seed_value)
    shuffled: dict[tuple, list[dict]] = {}
    for key in tables:  # 按 _plan_list 的插入顺序打乱，保证确定性
        bucket = [dict(cell) for cell in tables[key]]
        rng.shuffle(bucket)
        shuffled[key] = bucket
    targets = TIER_TARGETS
    counts = dict(QUOTAS)
    base_by_tier: dict[str, int] = {}
    cumulative = 0
    for tier, count in QUOTAS:
        base_by_tier[tier] = cumulative
        cumulative += count
    used: set[tuple] = set()
    picked_by_tier: dict[str, list[dict]] = {}
    tier_list = [tier for tier, _count in QUOTAS]
    for tier in SELECTION_TIER_ORDER:
        count = counts[tier]
        tier_plans = [plan for plan in plans if plan["tier"] == tier]
        picked: list[dict | None] = [None] * count
        target = targets[tier_list.index(tier)]
        base = base_by_tier[tier]
        for gender in ("男", "女"):
            wanted = target[gender]
            placed = 0
            for index in range(count):
                if placed >= wanted:
                    break
                if picked[index] is not None:
                    continue
                plan = tier_plans[index]
                seq = base + index + 1
                parity = 1 if seq % 2 else 2
                found = None
                for cell in shuffled[(plan["extra"], plan["scope"])]:
                    if cell["gender"] != gender:
                        continue
                    if _cell_key(cell) in used:
                        continue
                    if not v3._tier_match(cell["capacity"][parity], plan["tier"]):
                        continue
                    found = cell
                    break
                if found is not None:
                    used.add(_cell_key(found))
                    picked[index] = found
                    placed += 1
        # 性别目标不可达时（容量与去重约束）用任意性别补齐
        for index in range(count):
            if picked[index] is not None:
                continue
            plan = tier_plans[index]
            seq = base + index + 1
            parity = 1 if seq % 2 else 2
            for cell in shuffled[(plan["extra"], plan["scope"])]:
                if _cell_key(cell) in used:
                    continue
                if not v3._tier_match(cell["capacity"][parity], plan["tier"]):
                    continue
                used.add(_cell_key(cell))
                picked[index] = cell
                break
            if picked[index] is None:
                raise RuntimeError(
                    f"v4 场景选择失败：{tier} 层第 {seq} 个槽位（{plan['extra']}）无可用格子")
        picked_by_tier[tier] = picked
    selected: list[dict] = []
    for tier, _count in QUOTAS:
        selected.extend(picked_by_tier[tier])
    if len(selected) != POSITIVE_COUNT:
        raise RuntimeError(f"v4 场景选择数量错误：{len(selected)} != {POSITIVE_COUNT}")
    return selected


# ------------------------------------------------------------------ 档案生成
def _clean_tags(tags, has_pet: str | None) -> list[str]:
    """has_pet=无 时删掉养宠类兴趣标签，并用中性标签补齐到 3 个。"""
    cleaned = [tag for tag in (tags or []) if tag not in PET_TAGS] \
        if has_pet == "无" else list(tags or [])
    for fallback in FALLBACK_TAGS:
        if len(cleaned) >= 3:
            break
        if fallback not in cleaned:
            cleaned.append(fallback)
    return cleaned[:3]


def text_pet_conflicts(profile: dict) -> list[str]:
    """文本级宠物矛盾：宠物活动词与“不养/过敏”表述同时出现。"""
    text = f"{profile.get('self_intro') or ''} {profile.get('roommate_expectation') or ''}"
    pet_words = [word for word in PET_TEXT_WORDS if word in text]
    no_pet = [phrase for phrase in NO_PET_PHRASES if phrase in text]
    if pet_words and no_pet:
        return [f"文本含宠物活动词 {pet_words} 且含不养/过敏表述 {no_pet}"]
    return []


def _make_positive(plan: dict, cell: dict, seq: int, capacity: int, unbounded: int,
                   pool) -> dict:
    """按最终 slot=seq 与清洗后兴趣标签生成一个正向场景。"""
    spec = dict(plan, slot=seq, _pool=pool)
    store_id = cell["store_id"]
    gender = cell["gender"]
    lease_term = cell["lease_term"]
    # 第一次：拿到 has_pet / 原始兴趣标签（文本稍后丢弃）
    _applicant0, profile0, _preference0, _app_pref0, _must0 = v3._make_applicant(
        spec, store_id, gender, lease_term, AS_OF)
    cleaned_tags = _clean_tags(profile0.get("interest_tags"), profile0.get("has_pet"))
    store_name = rules.store_name(store_id) or str(store_id)
    # 用清洗后标签重建自我介绍；顺手规范模板里相邻句号重复的标点（v3 冻结文本
    # 有同样的 "。。" 历史瑕疵，v4 新文本不再保留）。
    self_intro = v3._self_intro(
        seq, store_name, profile0.get("occupation") or "",
        profile0.get("schedule_type") or "", plan.get("extra"),
        int(profile0.get("rent_budget") or 0), cleaned_tags).replace("。。", "。")
    # 第二次：用清洗后标签重建档案与自我介绍（slot=seq，昵称唯一）
    applicant, profile, preference, _app_pref, must_codes = v3._make_applicant(
        spec, store_id, gender, lease_term, AS_OF,
        tags_override=cleaned_tags, nickname=f"V4场景租客{seq:02d}",
        self_intro=self_intro)
    _ = applicant  # 规则对象由 v3 生成；标签/昵称不影响硬规则容量
    area = rules.area_of(store_id)
    tier_label = v3._tier_label(spec)
    suffix = {"store": "门店必须", "budget": "预算必须", "pet": "养宠必须"}.get(
        spec.get("extra"), "容量基线")
    target = min(DELIVER_COUNT, unbounded)
    moments = v3._moments(seq, store_name, profile["schedule_type"], profile["interest_tags"])
    return {
        "key": f"V4_{seq:02d}",
        "account": f"TEST_SCENARIO_V4_{seq:02d}",
        "slot": seq,
        "title": f"V4-{seq:02d} {store_name} · {gender} · {lease_term} · {suffix}",
        "run": True,
        "deliver_count": DELIVER_COUNT,
        "profile": profile,
        "preference": preference,
        "moments": moments,
        "expect": {
            "can_run": True,
            "blocker": None,
            "requested": DELIVER_COUNT,
            "target": target,
            "target_rule": TARGET_RULE,
            "ex_ante_eligible": capacity,
            "ex_ante_unbounded": unbounded,
            "note": (f"容量 {tier_label}：门店范围内硬可匹配 {capacity} 人"
                     f"（不限门店 {unbounded} 人）；target=min(8, {unbounded})={target}；"
                     f"交付要求 {DELIVER_COUNT} 人"),
        },
        "why": (f"门店×性别×租期格 {store_name}（{area}）/ {gender} / {lease_term}；"
                f"门店范围 {spec['scope']}；必须项 "
                f"{'、'.join(rules.DIM_NAMES[code] for code in must_codes)}；"
                f"容量 {tier_label}（eligible {capacity}，unbounded {unbounded}）"),
        "ex_ante_capacity": {
            "tier": spec["tier"],
            "tier_label": tier_label,
            "eligible": capacity,
            "eligible_unbounded": unbounded,
            "raw_cell": cell["raw_cell"],
            "store_scope": spec["scope"],
            "store_id": store_id,
            "store": store_name,
            "area": area,
            "gender": gender,
            "lease_term": lease_term,
            "must_dimensions": [rules.DIM_NAMES[code] for code in must_codes],
            "must_codes": list(must_codes),
            "requested": DELIVER_COUNT,
        },
    }


def _make_negative(source: dict, seq: int, kind: str) -> dict:
    """从正向场景派生一个 readiness 负向场景（缺动态 / 缺自我介绍）。"""
    profile = json.loads(json.dumps(source["profile"], ensure_ascii=False))
    preference = json.loads(json.dumps(source["preference"], ensure_ascii=False))
    profile["nickname"] = f"V4场景租客{seq:02d}"
    # 负向场景是“同一个申请人缺一块数据”，把文本里的来源序号改成本场景 slot，
    # 避免昵称 41 但自述“第 11 次”这种新造的编号矛盾。
    source_slot = source.get("slot")
    for field in ("self_intro", "roommate_expectation"):
        text = str(profile.get(field) or "")
        if source_slot:
            text = text.replace(f"第 {source_slot} 次", f"第 {seq} 次")
        profile[field] = text.replace("。。", "。")
    capacity = source["ex_ante_capacity"]
    store_name = capacity["store"]
    if kind == "moment":
        moments: list[str] = []
        blocker = "moment"
        title = f"V4-{seq:02d} 档案不完整：无租客动态"
        why = "负向 readiness：profile/preference 齐全，moments 为空，readiness 应在 moment 阻断"
    elif kind == "intro":
        profile["self_intro"] = ""
        moments = [
            f"昨天晚上在{store_name}附近跑了会儿步，回来洗了个澡就睡了。",
            "今天把房间里的衣服整理了一遍，准备这周末去看看房子。",
        ]
        blocker = "intro"
        title = f"V4-{seq:02d} 档案不完整：无自我介绍"
        why = ("负向 readiness：self_intro 为空；业务校验要求自我介绍必填，"
               "通过 API 建档应在保存阶段被拒收，run_matrix 需兼容这一可观测结果")
    else:  # pragma: no cover - 防御
        raise ValueError(f"未知负向类型：{kind}")
    return {
        "key": f"V4_{seq:02d}",
        "account": f"TEST_SCENARIO_V4_{seq:02d}",
        "slot": seq,
        "title": title,
        "run": False,
        "deliver_count": DELIVER_COUNT,
        "profile": profile,
        "preference": preference,
        "moments": moments,
        "expect": {
            "can_run": False,
            "blocker": blocker,
            "requested": DELIVER_COUNT,
            "note": why,
        },
        "why": why,
        "ex_ante_capacity": dict(
            capacity,
            tier="negative",
            tier_label="负向",
            source_key=source["key"],
            source_tier=capacity["tier"],
            source_gender=source["profile"]["gender"],
        ),
    }


def _negative_partition(positives: list[dict]) -> tuple[list[dict], list[dict]]:
    """把 8 个固定来源正向场景确定性切成 moment/intro 两族。

    约束：两族各自 4 个、都跨性别、都跨容量层（至少 2 层）；在满足约束的切法里
    选层分布最均衡的一种（每族理想 2 高 + 1 中 + 1 低），再按来源顺序取。
    """
    sources = [positives[index] for index in NEGATIVE_SOURCE_INDICES]
    ideal = {"high": 2, "medium": 1, "low": 1}

    def _ok(group: list[dict]) -> bool:
        genders = {item["profile"]["gender"] for item in group}
        tiers = {item["ex_ante_capacity"]["tier"] for item in group}
        return len(genders) == 2 and len(tiers) >= 2

    def _imbalance(group: list[dict]) -> int:
        counts = Counter(item["ex_ante_capacity"]["tier"] for item in group)
        return sum(abs(counts.get(tier, 0) - want) for tier, want in ideal.items())

    best: tuple | None = None
    for moment_indexes in itertools.combinations(range(len(sources)),
                                                 NEGATIVE_PARTITION_SIZE):
        moment_set = set(moment_indexes)
        moment_group = [sources[index] for index in sorted(moment_set)]
        intro_group = [sources[index] for index in range(len(sources))
                       if index not in moment_set]
        if not _ok(moment_group) or not _ok(intro_group):
            continue
        score = (_imbalance(moment_group) + _imbalance(intro_group), moment_indexes)
        if best is None or score < best[0]:
            best = (score, moment_group, intro_group)
    if best is None:
        raise RuntimeError(
            "v4 负向切分失败：8 个来源正向场景无法同时满足“两族各 4 个、"
            "都跨性别且都跨容量层”")
    return best[1], best[2]


# -------------------------------------------------------------------- 构建
def build(repo_root: Path | str = REPO, seed_value: int = SEED) -> dict:
    """生成并返回 v4 场景字典（纯函数，不写文件；重复构建字节一致）。"""
    root = Path(repo_root).resolve()
    seed_data = seedmod.load_seed(root)
    pool = seedmod.approved_candidates(seed_data)
    prefs = seed_data.preferences
    plans = _plan_list()
    tables: dict[tuple, list[dict]] = {}
    for plan in plans:
        key = (plan["extra"], plan["scope"])
        if key in tables:
            continue
        tables[key] = _capacity_table(plan["extra"], plan["scope"], pool, prefs,
                                      str(root), seed_value)
    chosen = _select(plans, tables, seed_value)

    positives: list[dict] = []
    for index, (plan, cell) in enumerate(zip(plans, chosen)):
        seq = index + 1
        spec = dict(plan, slot=seq, _pool=pool)
        capacity, unbounded = v3._capacity_for(
            spec, cell["store_id"], cell["gender"], cell["lease_term"], pool, prefs, AS_OF)
        if not v3._tier_match(capacity, plan["tier"]):
            raise RuntimeError(
                f"v4 内部错误：{plan['tier']} 层第 {seq} 个场景容量 {capacity} 不在层内")
        positives.append(_make_positive(plan, cell, seq, capacity, unbounded, pool))

    moment_sources, intro_sources = _negative_partition(positives)
    negatives: list[dict] = []
    for offset, source in enumerate(moment_sources):
        negatives.append(_make_negative(source, POSITIVE_COUNT + offset + 1, "moment"))
    for offset, source in enumerate(intro_sources):
        negatives.append(_make_negative(source, POSITIVE_COUNT + 4 + offset + 1, "intro"))

    scenarios = positives + negatives
    stores = [item["profile"]["store_id"] for item in positives]
    genders = [item["profile"]["gender"] for item in positives]
    leases = [item["profile"]["lease_term"] for item in positives]
    tiers = [item["ex_ante_capacity"]["tier"] for item in positives]
    targets = Counter(str(item["expect"]["target"]) for item in positives)
    must_plan = {
        code: [item["key"] for item in positives
               if code in item["ex_ante_capacity"]["must_codes"]]
        for code in ("store", "budget", "pet")
    }
    pet_tag_scenarios = []
    removed_total = 0
    for item in positives:
        seq = item["slot"]
        raw_tags = list(v3.TAG_SETS[(seq - 1) % len(v3.TAG_SETS)])
        removed = [tag for tag in raw_tags if tag in PET_TAGS]
        if removed:
            removed_total += len(removed)
            pet_tag_scenarios.append({"key": item["key"], "removed_count": len(removed)})
    return {
        "version": VERSION,
        "suite": VERSION,
        "seed": seed_value,
        "protocol_version": PROTOCOL_VERSION,
        "as_of": AS_OF.isoformat(),
        "scenario_count": len(scenarios),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "deliver_count": DELIVER_COUNT,
        "grid": {
            "axes": ["store_id", "gender", "lease_term"],
            "capacity_basis": ("approved_candidates + 同性 + 租期档差<2 + 双向必须项"
                               "（门店范围按申请方偏好）"),
            "tiers": {"high": "eligible>=8", "medium": "4-7", "low": "1-3"},
            "tier_quotas": dict(QUOTAS),
            "tier_counts": {tier: tiers.count(tier) for tier in ("high", "medium", "low")},
            "sampling": "deterministic-without-replacement（每层内按性别目标 + 最终 seq 奇偶容量）",
            "diversity": {
                "stores": len(set(stores)),
                "male": genders.count("男"),
                "female": genders.count("女"),
                "lease_terms": len(set(leases)),
            },
            "must_plan": must_plan,
            "labels": "pending-human/judge（本文件不含 gold 排序标签）",
            "negative_types": {"moment": 4, "intro": 4},
            "negative_sources": {
                "indices": list(NEGATIVE_SOURCE_INDICES),
                "moment": [item["ex_ante_capacity"]["source_key"] for item in negatives
                           if item["expect"]["blocker"] == "moment"],
                "intro": [item["ex_ante_capacity"]["source_key"] for item in negatives
                          if item["expect"]["blocker"] == "intro"],
            },
            "slot_rule": ("选项阶段用占位 slot=1 只算容量；选中后按最终顺序赋 "
                          "slot=seq(1..40)，nickname=V4场景租客{seq:02d}"),
            "target_rule": TARGET_RULE,
            "target_distribution": dict(sorted(targets.items(), key=lambda pair: int(pair[0]))),
            "text_cleaning": {
                "rule": ("has_pet=无 时移除养宠类兴趣标签并用中性标签补齐；"
                         "self_intro/moments 用清洗后标签重新生成"),
                "scenarios": pet_tag_scenarios,
                "removed_tags": removed_total,
            },
        },
        "scenarios": scenarios,
    }


def dump(data: dict) -> str:
    """确定性序列化（无时间戳；重复构建字节一致）。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# -------------------------------------------------------------------- 校验
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_profile_fields(profile: dict) -> list[str]:
    required = ("nickname", "gender", "birth_date", "rent_budget", "tidiness",
                "occupation", "lease_term", "store_id", "schedule_type", "has_pet",
                "smoking", "self_intro", "roommate_expectation", "interest_tags")
    return [f"profile 缺字段 {name}" for name in required if name not in profile]


def _check_preference_fields(preference: dict) -> list[str]:
    required = ("age_min", "age_max", "age_required", "budget_min", "budget_max",
                "budget_required", "tidiness_min", "tidiness_required", "store_scope",
                "store_required", "schedule_accept", "schedule_required", "lease_min",
                "lease_required", "pet_accept", "pet_required")
    return [f"preference 缺字段 {name}" for name in required if name not in preference]


def check(data: dict) -> list[str]:
    """校验 v4 场景文件的形状/配额/target/负向覆盖/文本自洽（不读磁盘）。"""
    errors: list[str] = []
    scenarios = data.get("scenarios") or []
    positives = [item for item in scenarios if item.get("run")]
    negatives = [item for item in scenarios if not item.get("run")]
    if data.get("version") != VERSION:
        errors.append(f"version 应为 {VERSION}，实际 {data.get('version')}")
    if data.get("protocol_version") != PROTOCOL_VERSION:
        errors.append(f"protocol_version 应为 {PROTOCOL_VERSION}，实际 "
                      f"{data.get('protocol_version')}")
    if data.get("seed") != SEED:
        errors.append(f"seed 应为 {SEED}，实际 {data.get('seed')}")
    if data.get("as_of") != AS_OF.isoformat():
        errors.append(f"as_of 应为 {AS_OF.isoformat()}，实际 {data.get('as_of')}")
    if data.get("scenario_count") != 48 or len(scenarios) != 48:
        errors.append(f"场景总数应为 48，实际 {data.get('scenario_count')}/{len(scenarios)}")
    if data.get("positive_count") != POSITIVE_COUNT or len(positives) != POSITIVE_COUNT:
        errors.append(f"正向数应为 {POSITIVE_COUNT}，实际 {data.get('positive_count')}/{len(positives)}")
    if data.get("negative_count") != NEGATIVE_COUNT or len(negatives) != NEGATIVE_COUNT:
        errors.append(f"负向数应为 {NEGATIVE_COUNT}，实际 {data.get('negative_count')}/{len(negatives)}")
    if data.get("deliver_count") != DELIVER_COUNT:
        errors.append(f"deliver_count 应为 {DELIVER_COUNT}")
    expected_order = ([f"V4_{index:02d}" for index in range(1, 49)]
                      + [f"TEST_SCENARIO_V4_{index:02d}" for index in range(1, 49)])
    actual_keys = [item.get("key") for item in scenarios]
    if actual_keys != expected_order[:48]:
        errors.append("场景 key 必须按 V4_01..V4_48 顺序排列")
    accounts = [item.get("account") for item in scenarios]
    if accounts != expected_order[48:]:
        errors.append("场景 account 必须按 TEST_SCENARIO_V4_01..48 顺序排列")
    slots = [item.get("slot") for item in scenarios]
    if slots != list(range(1, 49)):
        errors.append("场景 slot 必须按 1..48 顺序排列")
    nicknames = [item.get("profile", {}).get("nickname") for item in scenarios]
    expected_nicknames = [f"V4场景租客{index:02d}" for index in range(1, 49)]
    if nicknames != expected_nicknames:
        errors.append("昵称必须按 V4场景租客01..48 唯一且与 slot 对齐")

    # ---- 正向 ----
    tier_counts: Counter = Counter()
    cells: set[tuple] = set()
    for index, item in enumerate(positives):
        seq = index + 1
        key = item.get("key")
        capacity = item.get("ex_ante_capacity") or {}
        expect = item.get("expect") or {}
        profile = item.get("profile") or {}
        preference = item.get("preference") or {}
        tier = capacity.get("tier")
        eligible = capacity.get("eligible")
        unbounded = capacity.get("eligible_unbounded")
        tier_counts[tier] += 1
        if item.get("deliver_count") != DELIVER_COUNT:
            errors.append(f"{key} deliver_count != {DELIVER_COUNT}")
        if expect.get("can_run") is not True or expect.get("blocker") is not None:
            errors.append(f"{key} 正向场景 expect.can_run/blocker 错误")
        if expect.get("requested") != DELIVER_COUNT:
            errors.append(f"{key} expect.requested != {DELIVER_COUNT}")
        if not isinstance(eligible, int) or eligible < 1:
            errors.append(f"{key} 容量 eligible 非法：{eligible}")
        if not isinstance(unbounded, int) or unbounded < eligible:
            errors.append(f"{key} eligible_unbounded {unbounded} < eligible {eligible}")
        if tier == "high":
            if not (isinstance(eligible, int) and eligible >= 8):
                errors.append(f"{key} 高容量层 eligible<8：{eligible}")
        elif tier == "medium":
            if not (isinstance(eligible, int) and 4 <= eligible <= 7):
                errors.append(f"{key} 中容量层 eligible 越界：{eligible}")
        elif tier == "low":
            if not (isinstance(eligible, int) and 1 <= eligible <= 3):
                errors.append(f"{key} 低容量层 eligible 越界：{eligible}")
        else:
            errors.append(f"{key} 未知容量层：{tier}")
        target = expect.get("target")
        wanted_target = min(DELIVER_COUNT, unbounded) if isinstance(unbounded, int) else None
        if target != wanted_target:
            errors.append(f"{key} expect.target={target} 应为 min(8, {unbounded})={wanted_target}")
        if expect.get("target_rule") != TARGET_RULE:
            errors.append(f"{key} expect.target_rule != {TARGET_RULE!r}")
        if expect.get("ex_ante_eligible") != eligible:
            errors.append(f"{key} expect.ex_ante_eligible 与 capacity.eligible 不一致")
        if expect.get("ex_ante_unbounded") != unbounded:
            errors.append(f"{key} expect.ex_ante_unbounded 与 capacity.eligible_unbounded 不一致")
        cell = (profile.get("store_id"), profile.get("gender"), profile.get("lease_term"))
        if cell in cells:
            errors.append(f"{key} 正向场景存在重复格子 {cell}")
        cells.add(cell)
        errors.extend(f"{key} {reason}" for reason in _check_profile_fields(profile))
        errors.extend(f"{key} {reason}" for reason in _check_preference_fields(preference))
        if profile.get("has_pet") != "无":
            errors.append(f"{key} 正向场景 has_pet 应为 无（本套设计）")
        tags = profile.get("interest_tags") or []
        pet_tags = [tag for tag in tags if tag in PET_TAGS]
        if pet_tags:
            errors.append(f"{key} 兴趣标签未清洗养宠类：{pet_tags}")
        if len(tags) < 3:
            errors.append(f"{key} 兴趣标签少于 3 个：{tags}")
        intro = profile.get("self_intro") or ""
        expectation = profile.get("roommate_expectation") or ""
        if not intro:
            errors.append(f"{key} self_intro 为空")
        if f"第 {seq} 次" not in intro:
            errors.append(f"{key} self_intro 未使用最终 slot=seq 的口径（第 {seq} 次）")
        if f"第 {seq} 次" not in expectation:
            errors.append(f"{key} roommate_expectation 未使用最终 slot=seq 的口径（第 {seq} 次）")
        if "V3场景租客" in intro + expectation or "V3场景租客" in (profile.get("nickname") or ""):
            errors.append(f"{key} 文本仍残留 V3 场景昵称/口径")
        for field, text in (("self_intro", intro), ("roommate_expectation", expectation)):
            if "。。" in text:
                errors.append(f"{key} {field} 存在重复句号（文本未规范化）")
        errors.extend(f"{key} {reason}" for reason in text_pet_conflicts(profile))
        moments = item.get("moments") or []
        if not moments:
            errors.append(f"{key} moments 为空（正向场景 readiness 需要至少一条）")
        for tag, text in (("self_intro", intro), ("moments", " ".join(moments))):
            found = [word for word in PET_TEXT_WORDS if word in text]
            if found:
                errors.append(f"{key} {tag} 仍含养宠类活动词 {found}")
        consistency = assess_person(profile)
        if consistency["score"] <= 0:
            errors.append(f"{key} 档案文本自相矛盾：{consistency['reasons']}")

    if dict(tier_counts) != {"high": 16, "medium": 12, "low": 12}:
        errors.append(f"容量层配额不匹配：{dict(tier_counts)}")

    # ---- 负向 ----
    moment_count = sum(1 for item in negatives
                       if (item.get("expect") or {}).get("blocker") == "moment")
    intro_count = sum(1 for item in negatives
                      if (item.get("expect") or {}).get("blocker") == "intro")
    if moment_count != 4 or intro_count != 4:
        errors.append(f"负向类型数量错误：moment {moment_count} / intro {intro_count}")
    positive_by_key = {item["key"]: item for item in positives}
    source_indexes: list[int] = []
    for index, item in enumerate(negatives):
        seq = POSITIVE_COUNT + index + 1
        capacity = item.get("ex_ante_capacity") or {}
        expect = item.get("expect") or {}
        source_key = capacity.get("source_key")
        source = positive_by_key.get(source_key)
        if source is None:
            errors.append(f"{item.get('key')} 负向来源 {source_key!r} 不是正向场景")
            continue
        try:
            source_indexes.append(positives.index(source))
        except ValueError:  # pragma: no cover
            errors.append(f"{item.get('key')} 负向来源定位失败")
        if expect.get("can_run") is not False:
            errors.append(f"{item.get('key')} 负向场景 expect.can_run 应为 False")
        if expect.get("blocker") not in ("moment", "intro"):
            errors.append(f"{item.get('key')} 负向 blocker 非法：{expect.get('blocker')}")
        if item.get("deliver_count") != DELIVER_COUNT:
            errors.append(f"{item.get('key')} 负向 deliver_count 非法")
        profile = item.get("profile") or {}
        expectation = str(profile.get("roommate_expectation") or "")
        if f"第 {seq} 次" not in expectation:
            errors.append(f"{item.get('key')} roommate_expectation 未使用本场景 slot=seq 的序号")
        if "。。" in expectation or "。。" in str(profile.get("self_intro") or ""):
            errors.append(f"{item.get('key')} 负向文本存在重复句号")
        if expect.get("blocker") == "moment":
            if item.get("moments"):
                errors.append(f"{item.get('key')} moment 负向的 moments 必须为空")
            if f"第 {seq} 次" not in str(profile.get("self_intro") or ""):
                errors.append(f"{item.get('key')} 负向自我介绍未使用本场景 slot=seq 的序号")
        if expect.get("blocker") == "intro" and profile.get("self_intro"):
            errors.append(f"{item.get('key')} intro 负向的 self_intro 必须为空")
    if sorted(source_indexes) != sorted(NEGATIVE_SOURCE_INDICES):
        errors.append(f"负向来源索引应固定为 {list(NEGATIVE_SOURCE_INDICES)}，"
                      f"实际 {sorted(source_indexes)}")
    for blocker in ("moment", "intro"):
        group = [item for item in negatives
                 if (item.get("expect") or {}).get("blocker") == blocker]
        genders = {(item.get("profile") or {}).get("gender") for item in group}
        tiers = {(item.get("ex_ante_capacity") or {}).get("source_tier") for item in group}
        if len(genders) < 2:
            errors.append(f"{blocker} 负向未跨性别：{genders}")
        if len(tiers) < 2:
            errors.append(f"{blocker} 负向未跨容量层：{tiers}")

    grid = data.get("grid") or {}
    if grid.get("negative_types") != {"moment": 4, "intro": 4}:
        errors.append(f"grid.negative_types 错误：{grid.get('negative_types')}")
    if grid.get("target_rule") != TARGET_RULE:
        errors.append("grid.target_rule 与 expect 口径不一致")
    actual_moment = [item["ex_ante_capacity"]["source_key"] for item in negatives
                     if item["expect"]["blocker"] == "moment"]
    actual_intro = [item["ex_ante_capacity"]["source_key"] for item in negatives
                    if item["expect"]["blocker"] == "intro"]
    sources = grid.get("negative_sources") or {}
    if sources.get("indices") != list(NEGATIVE_SOURCE_INDICES):
        errors.append("grid.negative_sources.indices 非法")
    if sources.get("moment") != actual_moment or sources.get("intro") != actual_intro:
        errors.append("grid.negative_sources 与实际负向场景不一致")
    cleanup = grid.get("text_cleaning") or {}
    if not isinstance(cleanup.get("scenarios"), list):
        errors.append("grid.text_cleaning.scenarios 缺失")
    return errors


# ------------------------------------------------------------ MANIFEST/覆盖
def _manifest_file(base: Path, name: str, repo_root: Path) -> str:
    """MANIFEST 里记录仓库相对路径；临时目录回退文件名。"""
    try:
        return (Path(base) / name).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return name


def _pool_info(repo_root: Path | str = REPO) -> dict:
    """候选池指纹：base SQL 字节 + 解析后的成员/偏好 canonical JSON。"""
    root = Path(repo_root)
    seed_data = seedmod.load_seed(root)
    stats = seedmod.seed_stats(seed_data)
    source = Path(stats.get("source") or "")
    try:
        source_text = source.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        source_text = str(source)
    return {
        "source": source_text,
        "members": stats["members"],
        "approved": stats["approved"],
        "base_sql_sha256": freeze.base_sql_sha256(root),
        "pool_digest": freeze.pool_digest(seed_data),
    }


def _supply_additions(repo_root: Path | str = REPO) -> int:
    """eval profile 专属 SQL 目录里的供给写语句数（必须为 0）。"""
    return len(freeze.find_supply_writes(Path(repo_root) / "deploy" / "mysql" / "sql" / "eval"))


def build_manifest(scenarios_bytes: bytes, data: dict, repo_root: Path | str = REPO,
                   created_at: str | None = None,
                   base: Path | str | None = None) -> dict:
    """由场景字节 + 种子池生成 MANIFEST（scenarios sha256 是冻结核心）。"""
    root = Path(repo_root)
    base_dir = Path(base) if base else FROZEN_DIR
    return {
        "version": data.get("version", VERSION),
        "protocol_version": data.get("protocol_version", PROTOCOL_VERSION),
        "seed": data.get("seed", SEED),
        "as_of": data.get("as_of", AS_OF.isoformat()),
        "generator": "eval/build_v4_scenarios.py",
        "scenario_count": data.get("scenario_count", 48),
        "positive_count": data.get("positive_count", POSITIVE_COUNT),
        "negative_count": data.get("negative_count", NEGATIVE_COUNT),
        "deliver_count": data.get("deliver_count", DELIVER_COUNT),
        "scenarios": {
            "file": _manifest_file(base_dir, SCENARIOS_FILE, root),
            "sha256": _sha256_bytes(scenarios_bytes),
        },
        "labels": {"status": "pending", "method": LABELS_METHOD},
        "pool": _pool_info(root),
        "supply_additions": _supply_additions(root),
        "created_at": created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def dump_manifest(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def build_coverage(data: dict) -> str:
    """生成 COVERAGE.md 文本（自动生成，禁止手改；同输入字节一致）。"""
    positives = [item for item in data["scenarios"] if item.get("run")]
    negatives = [item for item in data["scenarios"] if not item.get("run")]
    grid = data.get("grid") or {}
    tier_labels = {"high": "高容量", "medium": "中容量", "low": "低容量"}
    lines: list[str] = []
    lines.append("# v4 覆盖报告（自动生成，禁止手改）")
    lines.append("")
    lines.append(f"- 生成命令：`python3 eval/build_v4_scenarios.py --write`")
    lines.append(f"- 场景总数：{data['scenario_count']}（正向 {data['positive_count']} / "
                 f"负向 {data['negative_count']}）")
    lines.append(f"- 协议：`{data['protocol_version']}`；seed=`{data['seed']}`；"
                 f"as_of=`{data['as_of']}`")
    lines.append(f"- target 口径：`{grid.get('target_rule', TARGET_RULE)}`")
    lines.append("")
    lines.append("## 容量层（正向）")
    lines.append("")
    lines.append("| 层 | 场景数 |")
    lines.append("|---|---|")
    for tier in ("high", "medium", "low"):
        lines.append(f"| {tier}（{tier_labels[tier]}） | "
                     f"{grid['tier_counts'].get(tier, 0)} |")
    lines.append("")
    lines.append("## 性别 / 租期")
    lines.append("")
    diversity = grid.get("diversity") or {}
    lines.append("| 维度 | 分布 |")
    lines.append("|---|---|")
    lines.append(f"| 性别 | 男 {diversity.get('male', 0)} / 女 {diversity.get('female', 0)} |")
    lease_counts = Counter(item["profile"]["lease_term"] for item in positives)
    lines.append("| 租期 | " + " / ".join(
        f"`{term}` {lease_counts.get(term, 0)}" for term in rules.LEASE_TERMS) + " |")
    lines.append("")
    lines.append("## 门店分布")
    lines.append("")
    lines.append("| 门店 | 场景数 |")
    lines.append("|---|---|")
    store_counts = Counter(item["ex_ante_capacity"]["store"] for item in positives)
    for store, count in sorted(store_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        lines.append(f"| {store} | {count} |")
    lines.append("")
    lines.append("## 必须项计划")
    lines.append("")
    lines.append("| 维度 | 场景数 | 场景 |")
    lines.append("|---|---|---|")
    must_plan = grid.get("must_plan") or {}
    for code in ("age", "budget", "pet", "schedule", "store"):
        keys = [item["key"] for item in positives
                if code in item["ex_ante_capacity"]["must_codes"]]
        lines.append(f"| {code} | {len(keys)} | {'、'.join(keys) if keys else '—'} |")
    lines.append("")
    lines.append("## target 分布")
    lines.append("")
    lines.append("| target | 场景数 |")
    lines.append("|---|---|")
    for target, count in sorted((grid.get("target_distribution") or {}).items(),
                                key=lambda pair: int(pair[0])):
        lines.append(f"| {target} | {count} |")
    lines.append("")
    lines.append("## 负向覆盖")
    lines.append("")
    lines.append("| blocker | 场景数 | 来源正向 | 层覆盖 | 性别覆盖 |")
    lines.append("|---|---|---|---|---|")
    sources = grid.get("negative_sources") or {}
    for blocker in ("moment", "intro"):
        group = [item for item in negatives
                 if (item.get("expect") or {}).get("blocker") == blocker]
        tiers = sorted({(item.get("ex_ante_capacity") or {}).get("source_tier") for item in group})
        genders = sorted({(item.get("profile") or {}).get("gender") for item in group})
        source_keys = sources.get(blocker) or []
        lines.append(f"| {blocker} | {len(group)} | {'、'.join(source_keys)} | "
                     f"{'、'.join(str(tier) for tier in tiers)} | {'、'.join(genders)} |")
    lines.append("")
    lines.append("## slot / 昵称 / 文本清洗")
    lines.append("")
    lines.append("- 正向 slot=seq 1..40，昵称 `V4场景租客01`..`V4场景租客40`（唯一，"
                 "自我介绍/期望同步使用最终序号）；负向 slot=41..48。")
    cleanup = grid.get("text_cleaning") or {}
    cleaned = cleanup.get("scenarios") or []
    lines.append(f"- 兴趣标签清洗：{len(cleaned)} 个正向场景移除了养宠类标签"
                 f"（共 {cleanup.get('removed_tags', 0)} 个标签），"
                 f"self_intro/moments 用清洗后标签重建。")
    if cleaned:
        lines.append("  " + "；".join(
            f"{item['key']}（{item['removed_count']} 个养宠类标签）" for item in cleaned))
    lines.append("")
    lines.append(f"- 正向场景数 {len(positives)}，负向场景数 {len(negatives)}。")
    lines.append("")
    lines.append("> 自动生成：`eval/build_v4_scenarios.py`；不要手改（`--check` 会比对）。")
    lines.append("")
    return "\n".join(lines)


# -------------------------------------------------------------------- 冻结校验
def verify(base: Path | str | None = None, repo_root: Path | str = REPO) -> list[str]:
    """只读校验当前冻结目录；返回错误清单（空 = 通过）。"""
    root = Path(repo_root)
    base_dir = Path(base) if base else FROZEN_DIR
    errors: list[str] = []
    scenarios_path = base_dir / SCENARIOS_FILE
    manifest_path = base_dir / MANIFEST_FILE
    coverage_path = base_dir / COVERAGE_FILE
    missing = [path.name for path in (scenarios_path, manifest_path, coverage_path)
               if not path.is_file()]
    if missing:
        return [f"冻结目录 {base_dir} 缺少文件：{missing}"]
    frozen_bytes = scenarios_path.read_bytes()
    try:
        frozen_text = frozen_bytes.decode("utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"冻结文件不是合法 UTF-8 JSON：{error}"]

    data = build(root)
    rebuilt = dump(data)
    if rebuilt != frozen_text:
        errors.append("scenarios.json 与 build() 重算结果不一致（生成器/种子/协议漂移或被手改）")
    errors.extend(check(data))

    expected = build_manifest(frozen_bytes, data, root,
                              created_at=manifest.get("created_at"), base=base_dir)
    for name in ("version", "protocol_version", "seed", "as_of", "generator",
                 "scenario_count", "positive_count", "negative_count", "deliver_count",
                 "supply_additions", "pool", "scenarios"):
        if manifest.get(name) != expected[name]:
            errors.append(f"MANIFEST.{name} 与重算结果不一致："
                          f"{manifest.get(name)!r} != {expected[name]!r}")
    if manifest.get("scenarios", {}).get("sha256") != _sha256_bytes(frozen_bytes):
        errors.append("MANIFEST.scenarios.sha256 与 scenarios.json 实际字节不一致")
    if not isinstance(manifest.get("created_at"), str) or not manifest.get("created_at"):
        errors.append("MANIFEST.created_at 缺失")

    labels_status = (manifest.get("labels") or {}).get("status")
    labels_path = base_dir / LABELS_FILE
    labels_errors: list[str] = []
    if labels_path.is_file():
        if labels_status != "ready":
            errors.append(f"labels.json 已存在但 MANIFEST.labels.status={labels_status!r}，应为 ready")
        import build_v4_labels  # 延迟导入，避免循环依赖
        labels_errors = build_v4_labels.check_labels_file(labels_path, data, manifest, root)
        errors.extend(f"labels.json: {item}" for item in labels_errors)
    else:
        if labels_status != "pending":
            errors.append(f"没有 labels.json 时 MANIFEST.labels.status 应为 pending，"
                          f"实际 {labels_status!r}")
        method = (manifest.get("labels") or {}).get("method")
        if not method:
            errors.append("MANIFEST.labels.method 缺失")

    coverage_text = build_coverage(data)
    if coverage_path.read_text(encoding="utf-8") != coverage_text:
        errors.append("COVERAGE.md 与自动生成内容不一致（自动生成文件不许手改）")
    return errors


# -------------------------------------------------------------------- 主入口
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成/校验 v4 评测集（40 正向 + 8 负向）")
    parser.add_argument("--check", action="store_true",
                        help="只读校验当前冻结（build 字节一致、MANIFEST sha、配额、target、文本）")
    parser.add_argument("--write", action="store_true",
                        help="写冻结文件（默认行为；显式指定也接受，与 --check 互斥）")
    parser.add_argument("--out", type=Path, default=None, help="冻结目录（默认 eval/frozen/v4）")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    base = args.out or FROZEN_DIR
    if args.check and args.write:
        parser.error("--check 与 --write 不能同时使用")
    if args.check:
        errors = verify(base, REPO)
        if errors:
            for error in errors:
                print(f"[FAIL] {error}")
            return 1
        print(f"[OK] v4 冻结校验通过：{base}")
        return 0

    data = build()
    errors = check(data)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        print("[FAIL] 校验未通过，未写入任何文件")
        return 1
    if (base / LABELS_FILE).is_file():
        print(f"[FAIL] {base / LABELS_FILE} 已存在：重冻场景会与已冻结标签不一致，"
              f"请先移除 labels.json 或改用标签工具")
        return 1
    text = dump(data)
    scenarios_bytes = text.encode("utf-8")
    base.mkdir(parents=True, exist_ok=True)
    (base / SCENARIOS_FILE).write_text(text, encoding="utf-8")
    manifest = build_manifest(scenarios_bytes, data, REPO, base=base)
    (base / MANIFEST_FILE).write_text(dump_manifest(manifest), encoding="utf-8")
    (base / COVERAGE_FILE).write_text(build_coverage(data), encoding="utf-8")
    if not args.quiet:
        print(f"写入 {base / SCENARIOS_FILE}")
        print(f"写入 {base / MANIFEST_FILE}")
        print(f"写入 {base / COVERAGE_FILE}")
        print(f"scenarios sha256={manifest['scenarios']['sha256']}")
        print(f"场景 {data['scenario_count']} 个（正向 {data['positive_count']} / "
              f"负向 {data['negative_count']}），seed={data['seed']}，as_of={data['as_of']}")
        print(f"容量层 {data['grid']['tier_counts']}，性别 "
              f"男 {data['grid']['diversity']['male']} / 女 {data['grid']['diversity']['female']}")
        targets = Counter(item["expect"]["target"] for item in data["scenarios"] if item["run"])
        print(f"target 分布：{dict(sorted(targets.items()))}")
        print(f"pool digest={manifest['pool']['pool_digest']}")
        print(f"supply_additions={manifest['supply_additions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
