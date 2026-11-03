#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v3 冻结场景集（离线可复现，不连数据库、不调模型）。

协议（Lead 批准，2026-11）：

* 共 10 个场景：8 个正向 + 2 个负向 readiness（缺动态 / 缺自我介绍），
  账号固定 TEST_SCENARIO_V3_01 ~ TEST_SCENARIO_V3_10，交付要求 8 人；
* 正向场景 = 门店 × 性别 × 租期档 的格子。先在 approved_candidates 上按
  lib.rules 算每格 eligible（同性 + 租期档差 < 2 + 双方必须项，门店范围按
  申请方自己的门店范围界定容量），再按容量分三层：
  3 个高（eligible >= 8）、3 个中（4-7）、2 个低（1-3）；
* 抽样用 seed=20261104 的确定性无放回抽样（random.Random，不依赖进程顺序），
  并强制满足：男女各 4 个、至少 4 个不同租期档、8 个场景 8 家不同门店、
  每个正向场景 eligible >= 1；
* 申请档案/偏好按固定规则从格子现生成：不复制任何种子成员文本；
  偏好必须项 = 年龄 + 作息，另外 2 个场景加「门店必须」、2 个加「预算必须」、
  1 个加「宠物必须」（必须是 2-4 项，与业务校验一致）。

产物：eval/frozen/v3/scenarios.json（版本化、确定性：不写构建时间戳）。
运行：python3 eval/build_v3_scenarios.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from lib import rules, seed as seedmod  # noqa: E402

VERSION = "v3"
SUITE = "v3"
PROTOCOL_VERSION = "v3-2026-11-04"
SEED = 20261104
AS_OF = date(2026, 11, 4)
DELIVER_COUNT = 8
POSITIVE_COUNT = 8
NEGATIVE_COUNT = 2
ACCOUNT_PREFIX = "TEST_SCENARIO_V3_"
FROZEN_DIR = EVAL_DIR / "frozen" / "v3"
SCENARIOS_FILE = "scenarios.json"
TARGET_STORES = 8

# 兴趣标签必须取自种子库 interest_tag 词表（保存档案会校验），按场景取固定三条
TAG_SETS = (
    ("看电影", "听音乐", "看纪录片"),
    ("跑步", "健身", "羽毛球"),
    ("咖啡", "探店", "烘焙"),
    ("看展", "摄影", "陶艺"),
    ("爬山", "骑行", "露营"),
    ("小说", "历史", "心理学"),
    ("桌游", "剧本杀", "密室逃脱"),
    ("养猫", "撸猫", "宠物摄影"),
    ("游泳", "瑜伽", "篮球"),
    ("听播客", "书法", "绘画"),
)

OCCUPATIONS = (
    "数据分析师", "会计", "行政专员", "运维工程师", "中学教师",
    "市场专员", "护理师", "物流调度", "翻译", "室内设计师",
)

# 每个正向场景的抽样规格：extra=额外的「必须项」，scope=申请方门店范围（容量边界）
SLOT_SPECS = (
    {"slot": 1, "extra": None, "scope": "同片区", "tier": "high"},
    {"slot": 2, "extra": None, "scope": "同片区", "tier": "high"},
    {"slot": 3, "extra": None, "scope": "同片区", "tier": "high"},
    {"slot": 4, "extra": "store", "scope": "同门店", "tier": "medium"},
    {"slot": 5, "extra": "budget", "scope": "同门店", "tier": "medium", "budget_width": 800},
    {"slot": 6, "extra": "store", "scope": "同门店", "tier": "medium"},
    {"slot": 7, "extra": "budget", "scope": "同门店", "tier": "low", "budget_width": 400},
    {"slot": 8, "extra": "pet", "scope": "同门店", "tier": "low"},
)

TIER_LIMITS = {"high": (8, None), "medium": (4, 7), "low": (1, 3)}

TIER_LABELS = {"high": "高容量", "medium": "中容量", "low": "低容量"}

# 出生月日固定在前十个月，保证不跨生日、年龄与 as_of 一致且可复现
BIRTH_DAYS = ((2, 11), (4, 19), (6, 6), (8, 27), (1, 15),
              (3, 23), (5, 9), (7, 21), (9, 12), (10, 18))


def _tier_of(capacity: int) -> str:
    if capacity >= 8:
        return "high"
    if capacity >= 4:
        return "medium"
    if capacity >= 1:
        return "low"
    return "none"


def _tier_match(capacity: int, tier: str) -> bool:
    low, high = TIER_LIMITS[tier]
    return capacity >= low and (high is None or capacity <= high)


def _median(values) -> int | None:
    cleaned = sorted(value for value in values if value is not None)
    return cleaned[len(cleaned) // 2] if cleaned else None


def _mode_schedule(candidates) -> str:
    counts: dict[str, int] = {}
    for member in candidates:
        counts[member.schedule_type] = counts.get(member.schedule_type, 0) + 1
    order = {name: index for index, name in enumerate(rules.SCHEDULE_TYPES)}
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], order.get(pair[0], 99)))
    return ranked[0][0] if ranked else "正常作息"


def _raw_cell(pool, store_id: int, gender: str, lease_term: str) -> list:
    """同门店、同性别、租期档位差 < 2 的候选（容量评估的基准池）。"""
    out = []
    for member in pool:
        if member.gender != gender or member.store_id != store_id:
            continue
        gap = rules.term_gap(member.lease_term, lease_term)
        if gap is None or gap >= rules.LEASE_TERM_GAP_LIMIT:
            continue
        out.append(member)
    return out


def _in_scope(member, applicant_store_id: int, scope: str) -> bool:
    if scope == "同门店":
        return member.store_id == applicant_store_id
    if scope == "同片区":
        return rules.area_of(member.store_id) == rules.area_of(applicant_store_id)
    return True


def _scope_candidates(pool, store_id: int, gender: str, lease_term: str, scope: str) -> list:
    out = []
    for member in pool:
        if member.gender != gender or not _in_scope(member, store_id, scope):
            continue
        gap = rules.term_gap(member.lease_term, lease_term)
        if gap is None or gap >= rules.LEASE_TERM_GAP_LIMIT:
            continue
        out.append(member)
    return out


def _acceptable_schedules(schedule: str, slot: int) -> list[str]:
    accepted = [schedule]
    if schedule != "正常作息" and slot % 2 == 0:
        accepted.append("正常作息")
    return accepted


def _make_applicant(spec: dict, store_id: int, gender: str, lease_term: str,
                    as_of: date = AS_OF):
    """按格子生成申请方：档案 + 偏好 + 参与规则判定的 Member/Preference。"""
    slot = spec["slot"]
    pool = spec["_pool"]
    cell_pool = _raw_cell(pool, store_id, gender, lease_term)
    age = _median([rules.age_of(member.birth_date, as_of) for member in cell_pool]) or 27
    budget = _median([member.rent_budget for member in cell_pool]) or 3500
    schedule = _mode_schedule(cell_pool)
    month, day = BIRTH_DAYS[(slot - 1) % len(BIRTH_DAYS)]
    birth = date(as_of.year - age, month, day)
    store_name = rules.store_name(store_id) or str(store_id)
    occupation = OCCUPATIONS[(slot - 1) % len(OCCUPATIONS)]
    tags = list(TAG_SETS[(slot - 1) % len(TAG_SETS)])
    must_codes = ["age", "schedule"]
    extra = spec.get("extra")
    if extra:
        must_codes.append(extra)

    profile = {
        "nickname": f"V3场景租客{slot:02d}",
        "gender": gender,
        "birth_date": birth.isoformat(),
        "rent_budget": budget,
        "tidiness": "整洁" if slot % 2 else "一般",
        "occupation": occupation,
        "lease_term": lease_term,
        "store_id": store_id,
        "schedule_type": schedule,
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": _self_intro(slot, store_name, occupation, schedule, extra, budget, tags),
        "roommate_expectation": _expectation(slot, store_name, age, extra, budget),
        "interest_tags": tags,
    }

    budget_width = spec.get("budget_width", 900)
    preference = {
        "age_min": max(18, age - 3),
        "age_max": min(80, age + 4),
        "age_required": "必须",
        "budget_min": max(800, budget - budget_width),
        "budget_max": min(20000, budget + budget_width),
        "budget_required": "必须" if extra == "budget" else "加分",
        "tidiness_min": "一般",
        "tidiness_required": "加分",
        "store_scope": spec["scope"],
        "store_required": "必须" if extra == "store" else "加分",
        "schedule_accept": _acceptable_schedules(schedule, slot),
        "schedule_required": "必须",
        "lease_min": "不限",
        "lease_required": "加分",
        "pet_accept": "不接受" if extra == "pet" else "接受",
        "pet_required": "必须" if extra == "pet" else "加分",
    }

    member = seedmod.member_from_payload(profile)
    prefs = seedmod.preference_from_payload(preference)
    return member, profile, preference, prefs, must_codes


def _self_intro(slot: int, store_name: str, occupation: str, schedule: str,
                extra: str | None, budget: int, tags: list[str]) -> str:
    """生成自我介绍：固定模板，不复制任何种子成员文本。"""
    sleep = {
        "早睡早起": "晚上十一点前就休息，早上起得也早",
        "正常作息": "十二点左右睡，周末会稍微睡个懒觉",
        "夜猫子": "睡得偏晚，一般一两点才休息，会戴耳机",
    }.get(schedule, "作息比较规律")
    weekend = {
        "早睡早起": "周末一般去公园走走，回来把房间和厨房都擦一遍",
        "正常作息": "周末做两顿饭、看部电影，公共区域用完顺手收拾",
        "夜猫子": "周末晚上比较精神，会打会儿游戏或者看纪录片",
    }.get(schedule, "周末收拾房间、看看书")
    extra_sentence = ""
    if extra == "store":
        extra_sentence = f"这次换房子优先看{store_name}，通勤近一点最重要。"
    elif extra == "budget":
        extra_sentence = f"预算卡得比较紧，月租希望控制在 {budget} 元上下。"
    elif extra == "pet":
        extra_sentence = "对动物毛发有点过敏，希望室友不养宠物。"
    return (
        f"我第 {slot} 次来这座城市工作，在{store_name}附近做{occupation}。"
        f"平时{sleep}，工作日节奏固定，下班回来不太折腾。"
        f"{weekend}。不抽烟，也不养宠物，{extra_sentence or '生活比较安静'}。"
        f"最近常做的事是{'、'.join(tags[:2])}，希望遇到好相处的室友。"
    )


def _expectation(slot: int, store_name: str, age: int, extra: str | None, budget: int) -> str:
    """生成室友期望：把必须项写成一句人话，与偏好字段保持一致。"""
    parts = [f"这是我第 {slot} 次在这座城市找合租，希望遇到能长期相处的室友。",
             f"希望室友和我年龄差不多（我今年 {age} 岁），作息能合得来，"
             f"公共区域一起保持干净。"]
    if extra == "store":
        parts.append(f"最好也住在{store_name}附近，通勤方便一点。")
    elif extra == "budget":
        parts.append(f"大家的租金水平接近一些，我会控制在 {budget} 元左右。")
    elif extra == "pet":
        parts.append("我不太能接受室友养宠物，希望理解。")
    parts.append("有事提前说一声，相处简单一点就好。")
    return "".join(parts)


def _moments(slot: int, store_name: str, schedule: str, tags: list[str]) -> list[str]:
    """生成 2-3 条租客动态（正向场景 readiness 需要至少一条）。"""
    sleep = {
        "早睡早起": "十一点熄灯，早上六点多自然醒",
        "正常作息": "十二点前躺下，早上八点前出门",
        "夜猫子": "一点多才睡，早上多赖一会儿",
    }.get(schedule, "作息规律")
    return [
        f"下班顺路在{store_name}附近买了个晚饭，回来把厨房台面擦干净才坐下。",
        f"这两天{sleep}，睡前把第二天要穿的衣服都放好了。",
        f"周末打算约朋友去{'、'.join(tags[1:])}，顺便把公共区域拖一遍。",
    ]


def _eligible(applicant, applicant_pref, candidates, prefs, as_of: date) -> list:
    """按双向硬规则筛出可直接交付的候选（缺少偏好无法验证的不算）。"""
    out = []
    for member in candidates:
        preference = prefs.get(member.id)
        if preference is None:
            continue
        if rules.is_hard_eligible(applicant, applicant_pref, member, preference, as_of):
            out.append(member)
    return out


def _capacity_for(spec: dict, store_id: int, gender: str, lease_term: str,
                  pool, prefs, as_of: date) -> tuple[int, int]:
    """算这一格的容量：scoped（申请方门店范围之内）与 unbounded（忽略门店偏好）。"""
    applicant, _profile, _pref, applicant_pref, _must = _make_applicant(
        spec, store_id, gender, lease_term, as_of)
    scoped_pool = _scope_candidates(pool, store_id, gender, lease_term, spec["scope"])
    scoped = _eligible(applicant, applicant_pref, scoped_pool, prefs, as_of)
    unbounded_pool = []
    for member in pool:
        if member.gender != gender:
            continue
        gap = rules.term_gap(member.lease_term, lease_term)
        if gap is not None and gap < rules.LEASE_TERM_GAP_LIMIT:
            unbounded_pool.append(member)
    unbounded = _eligible(applicant, applicant_pref, unbounded_pool, prefs, as_of)
    return len(scoped), len(unbounded)


def _slot_options(spec: dict, pool, prefs, as_of: date) -> list[dict]:
    """枚举该场景所有满足容量分层的格子。"""
    options = []
    for store_id in sorted({member.store_id for member in pool if member.store_id}):
        for gender in ("男", "女"):
            for lease_term in rules.LEASE_TERMS:
                capacity, unbounded = _capacity_for(
                    spec, store_id, gender, lease_term, pool, prefs, as_of)
                if not _tier_match(capacity, spec["tier"]):
                    continue
                options.append({
                    "store_id": store_id,
                    "gender": gender,
                    "lease_term": lease_term,
                    "capacity": capacity,
                    "unbounded": unbounded,
                    "raw_cell": len(_raw_cell(pool, store_id, gender, lease_term)),
                })
    return options


def _sample_cells(specs: list[dict], options: list[list[dict]],
                  seed_value: int) -> list[dict]:
    """确定性无放回抽样：随机打乱候选格子后用回溯满足全部多样性约束。"""
    rng = random.Random(seed_value)
    shuffled = []
    for items in options:
        bucket = list(items)
        rng.shuffle(bucket)
        shuffled.append(bucket)
    order = sorted(range(len(specs)), key=lambda index: (len(shuffled[index]), specs[index]["slot"]))
    chosen: list[dict | None] = [None] * len(specs)

    def compatible(index: int, option: dict) -> bool:
        used_stores = {item["store_id"] for item in chosen if item is not None}
        if option["store_id"] in used_stores:
            return False
        picked = [item for item in chosen if item is not None]
        male = len([item for item in picked if item["gender"] == "男"])
        female = len([item for item in picked if item["gender"] == "女"])
        male += 1 if option["gender"] == "男" else 0
        female += 1 if option["gender"] == "女" else 0
        # 8 个正向场景要求男女各 >= 4，因此必须正好 4/4
        if male > POSITIVE_COUNT // 2 or female > POSITIVE_COUNT // 2:
            return False
        leases = {item["lease_term"] for item in picked} | {option["lease_term"]}
        remaining = len(specs) - len(picked) - 1
        if len(leases) + remaining < 4:
            return False
        return True

    def dfs(position: int) -> bool:
        if position == len(order):
            return True
        index = order[position]
        for option in shuffled[index]:
            if not compatible(index, option):
                continue
            chosen[index] = option
            if dfs(position + 1):
                return True
            chosen[index] = None
        return False

    if not dfs(0):
        raise RuntimeError("v3 场景抽样失败：容量分层 + 多样性约束无解")
    return [item for item in chosen if item is not None]


def _tier_label(spec: dict) -> str:
    return TIER_LABELS[spec["tier"]]


def _build_positive(spec: dict, cell: dict, applicant, profile, preference,
                    must_codes: list[str]) -> dict:
    slot = spec["slot"]
    extra = spec.get("extra")
    title_suffix = {
        None: "容量基线",
        "store": "门店必须",
        "budget": "预算必须",
        "pet": "养宠必须",
    }[extra]
    expect_note = (f"容量分层 {_tier_label(spec)}：门店范围内硬可匹配 "
                   f"{cell['capacity']} 人（不限门店 {cell['unbounded']} 人）；"
                   f"交付要求 {DELIVER_COUNT} 人")
    return {
        "key": f"V3_{slot:02d}",
        "account": f"{ACCOUNT_PREFIX}{slot:02d}",
        "title": (f"V3-{slot:02d} {rules.store_name(cell['store_id'])} · "
                  f"{cell['gender']} · {cell['lease_term']} · {title_suffix}"),
        "run": True,
        "deliver_count": DELIVER_COUNT,
        "profile": profile,
        "preference": preference,
        "moments": _moments(slot, rules.store_name(cell["store_id"]),
                            profile["schedule_type"], profile["interest_tags"]),
        "expect": {
            "can_run": True,
            "blocker": None,
            "requested": DELIVER_COUNT,
            "ex_ante_eligible": cell["capacity"],
            "ex_ante_unbounded": cell["unbounded"],
            "note": expect_note,
        },
        "why": (f"门店×性别×租期格：{rules.store_name(cell['store_id'])}"
                f"（{rules.area_of(cell['store_id'])}）/ {cell['gender']} / "
                f"{cell['lease_term']}；门店范围 {spec['scope']}；"
                f"必须项 {'、'.join(rules.DIM_NAMES[code] for code in must_codes)}；"
                f"容量分层 {_tier_label(spec)}（eligible {cell['capacity']}）"),
        "ex_ante_capacity": {
            "tier": spec["tier"],
            "tier_label": _tier_label(spec),
            "eligible": cell["capacity"],
            "eligible_unbounded": cell["unbounded"],
            "raw_cell": cell["raw_cell"],
            "store_scope": spec["scope"],
            "store_id": cell["store_id"],
            "store": rules.store_name(cell["store_id"]),
            "area": rules.area_of(cell["store_id"]),
            "gender": cell["gender"],
            "lease_term": cell["lease_term"],
            "must_dimensions": [rules.DIM_NAMES[code] for code in must_codes],
            "must_codes": list(must_codes),
            "requested": DELIVER_COUNT,
        },
    }


def _build_negative(slot: int, cell: dict, profile: dict, preference: dict,
                    capacity: int, reason: str) -> dict:
    kind = "moment" if reason == "moment" else "intro"
    if reason == "moment":
        moments: list[str] = []
        expect = {
            "can_run": False,
            "blocker": "moment",
            "requested": DELIVER_COUNT,
            "note": "有档案、有偏好、没有动态：readiness 应在「租客动态」阻断，不调模型",
        }
        title = f"V3-{slot:02d} 档案不完整：无租客动态"
        why = "负向 readiness：profile/preference 齐全，moments 为空，readiness 应在 moment 项阻断"
    else:
        profile = dict(profile)
        profile["self_intro"] = ""
        moments = [
            f"昨天晚上在{rules.store_name(cell['store_id'])}附近跑了会儿步，回来洗了个澡就睡了。",
            "今天把房间里的衣服整理了一遍，准备这周末去看看房子。",
        ]
        expect = {
            "can_run": False,
            "blocker": "intro",
            "requested": DELIVER_COUNT,
            "note": ("自我介绍是保存档案的业务必填项：通过 API 建档会在保存阶段被拒收；"
                     "若允许空值，readiness 应在「自我介绍」项阻断"),
        }
        title = f"V3-{slot:02d} 档案不完整：无自我介绍"
        why = ("负向 readiness：self_intro 为空；注意业务校验要求自我介绍必填，"
               "run_matrix 需兼容「建档即被拒」这一可观测结果")
    return {
        "key": f"V3_{slot:02d}",
        "account": f"{ACCOUNT_PREFIX}{slot:02d}",
        "title": title,
        "run": False,
        "deliver_count": DELIVER_COUNT,
        "profile": profile,
        "preference": preference,
        "moments": moments,
        "expect": expect,
        "why": why,
        "ex_ante_capacity": {
            "tier": "negative",
            "tier_label": "负向",
            "eligible": capacity,
            "store_scope": "同片区",
            "store_id": cell["store_id"],
            "store": rules.store_name(cell["store_id"]),
            "area": rules.area_of(cell["store_id"]),
            "gender": cell["gender"],
            "lease_term": cell["lease_term"],
            "must_dimensions": ["年龄", "作息"],
            "must_codes": ["age", "schedule"],
            "requested": DELIVER_COUNT,
        },
    }


def _negative_cell(options_by_slot: list[list[dict]], used_stores: set) -> dict:
    """负向场景复用高容量格子的协议生成规则，但门店不与正向场景重复。"""
    base = {spec["slot"]: items for spec, items in zip(SLOT_SPECS, options_by_slot)}
    for option in base.get(1) or []:
        if option["store_id"] not in used_stores:
            return option
    for items in options_by_slot:
        for option in items:
            if option["store_id"] not in used_stores:
                return option
    raise RuntimeError("找不到可用于负向场景的门店格子")


def build_scenarios(repo_root: Path | str = REPO, as_of: date = AS_OF,
                    seed_value: int = SEED) -> dict:
    """生成并返回 v3 场景字典（纯函数，不写文件）。"""
    root = Path(repo_root)
    seed_data = seedmod.load_seed(root)
    pool = seedmod.approved_candidates(seed_data)
    prefs = seed_data.preferences
    specs = [dict(item, _pool=pool) for item in SLOT_SPECS]
    options: list[list[dict]] = []
    for spec in specs:
        items = _slot_options(spec, pool, prefs, as_of)
        if not items:
            raise RuntimeError(
                f"场景 {spec['slot']:02d} 在 {spec['tier']} 层没有可用格子，协议无解")
        options.append(items)
    chosen = _sample_cells(specs, options, seed_value)

    scenarios = []
    for spec, cell in zip(specs, chosen):
        applicant, profile, preference, _applicant_pref, must_codes = _make_applicant(
            spec, cell["store_id"], cell["gender"], cell["lease_term"], as_of)
        scenarios.append(_build_positive(spec, cell, applicant, profile, preference, must_codes))

    used_stores = {cell["store_id"] for cell in chosen}
    negative_cell = _negative_cell(options, used_stores)
    negative_spec = {"slot": 9, "extra": None, "scope": "同片区", "tier": "high", "_pool": pool}
    _applicant, profile9, preference9, _pref9, _must9 = _make_applicant(
        negative_spec, negative_cell["store_id"], negative_cell["gender"],
        negative_cell["lease_term"], as_of)
    scenarios.append(_build_negative(9, negative_cell, profile9, preference9,
                                     negative_cell["capacity"], "moment"))
    negative_spec10 = {"slot": 10, "extra": None, "scope": "同片区", "tier": "high", "_pool": pool}
    _applicant, profile10, preference10, _pref10, _must10 = _make_applicant(
        negative_spec10, negative_cell["store_id"], negative_cell["gender"],
        negative_cell["lease_term"], as_of)
    scenarios.append(_build_negative(10, negative_cell, profile10, preference10,
                                     negative_cell["capacity"], "intro"))

    positives = [item for item in scenarios if item["run"]]
    stores = [item["ex_ante_capacity"]["store_id"] for item in positives]
    genders = [item["profile"]["gender"] for item in positives]
    leases = [item["profile"]["lease_term"] for item in positives]
    tiers = [item["ex_ante_capacity"]["tier"] for item in positives]
    return {
        "version": VERSION,
        "suite": SUITE,
        "seed": seed_value,
        "protocol_version": PROTOCOL_VERSION,
        "as_of": as_of.isoformat(),
        "scenario_count": len(scenarios),
        "positive_count": len(positives),
        "negative_count": len(scenarios) - len(positives),
        "deliver_count": DELIVER_COUNT,
        "grid": {
            "axes": ["store_id", "gender", "lease_term"],
            "capacity_basis": "approved_candidates + 同性 + 租期档差<2 + 双向必须项（门店范围按申请方偏好）",
            "tiers": {"high": "eligible>=8", "medium": "4-7", "low": "1-3"},
            "tier_counts": {tier: tiers.count(tier) for tier in ("high", "medium", "low")},
            "sampling": "deterministic-without-replacement",
            "diversity": {
                "stores": len(set(stores)),
                "male": genders.count("男"),
                "female": genders.count("女"),
                "lease_terms": len(set(leases)),
            },
            "must_plan": {
                "store": [item["key"] for item in positives
                          if "store" in item["ex_ante_capacity"]["must_codes"]],
                "budget": [item["key"] for item in positives
                           if "budget" in item["ex_ante_capacity"]["must_codes"]],
                "pet": [item["key"] for item in positives
                        if "pet" in item["ex_ante_capacity"]["must_codes"]],
            },
        },
        "scenarios": scenarios,
    }


def dump_scenarios(data: dict) -> str:
    """序列化成确定性的 JSON 文本（无时间戳，重复构建字节一致）。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def scenarios_path(out_dir: Path | str | None = None) -> Path:
    base = Path(out_dir) if out_dir else FROZEN_DIR
    return base / SCENARIOS_FILE


def write_scenarios(data: dict, out_dir: Path | str | None = None) -> Path:
    path = scenarios_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_scenarios(data), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 v3 冻结场景集")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出目录（默认 eval/frozen/v3）")
    parser.add_argument("--quiet", action="store_true", help="只输出路径")
    args = parser.parse_args(argv)
    data = build_scenarios()
    path = write_scenarios(data, args.out)
    if args.quiet:
        print(path)
        return 0
    positives = [item for item in data["scenarios"] if item["run"]]
    print(f"写入 {path}")
    print(f"场景 {data['scenario_count']} 个（正向 {data['positive_count']} / "
          f"负向 {data['negative_count']}），seed={data['seed']}，as_of={data['as_of']}")
    for item in positives:
        cap = item["ex_ante_capacity"]
        print(f"  {item['key']} {cap['store']} {cap['gender']} {cap['lease_term']} "
              f"cap={cap['eligible']}({cap['tier']}) must={'、'.join(cap['must_dimensions'])}")
    print(f"多样性：门店 {data['grid']['diversity']['stores']} 个，"
          f"男 {data['grid']['diversity']['male']} / 女 {data['grid']['diversity']['female']}，"
          f"租期档 {data['grid']['diversity']['lease_terms']} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())