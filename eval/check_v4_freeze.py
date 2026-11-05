#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 场景/标签冻结守卫（fail-closed；离线，不连数据库、不调模型）。

校验内容：
1. scenarios.json 与 MANIFEST.scenarios.sha256 一致；
2. 48 场景 = 40 正向 + 8 负向；容量层 16/12/12；正向格子无重复；
   key / account / slot / 昵称按 V4_01..V4_48 顺序唯一；
3. 每个正向 expect.target = min(8, eligible_unbounded)、target_rule 固定；
4. 正向 profile 文本自洽：本地“宠物活动词 + 不养/过敏”矛盾规则 fail-closed，
   并调用 human_eval/data_consistency.assess_person 要求 score > 0；
5. 负向 blocker moment/intro 各 4，且两族都跨容量层、跨性别；
6. labels 状态：没有 labels.json 时 MANIFEST.labels.status 必须 pending；
   有 labels.json 时必须 ready，且逐条 schema（pair_id/delivered/applicant/
   candidate/score 0-3/annotator）与“覆盖 40 正向”校验通过；
7. MANIFEST.pool 的 members/approved/base SQL 指纹/候选池 digest 与当前种子一致，
   supply_additions 与实际扫描一致且必须为 0。

用法：python3 eval/check_v4_freeze.py [--frozen-dir PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
for _path in (str(EVAL_DIR), str(REPO)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
HUMAN_EVAL_DIR = EVAL_DIR / "human_eval"
if str(HUMAN_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(HUMAN_EVAL_DIR))

import build_v4_scenarios as v4  # noqa: E402
from data_consistency import assess_person  # noqa: E402
from lib import freeze, seed as seedmod  # noqa: E402

BASE = EVAL_DIR / "frozen" / "v4"
SCENARIOS_FILE = "scenarios.json"
MANIFEST_FILE = "MANIFEST.json"
LABELS_FILE = "labels.json"
TIER_QUOTAS = {"high": 16, "medium": 12, "low": 12}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_text(source: dict) -> list[str]:
    """单个正向 profile 的文本自洽错误（本地规则 + assess_person）。"""
    errors: list[str] = []
    profile = source.get("profile") or {}
    errors.extend(v4.text_pet_conflicts(profile))
    result = assess_person(profile)
    if result["score"] <= 0:
        errors.append(f"assess_person=0：{result['reasons']}")
    return errors


def check_scenarios(data: dict) -> list[str]:
    """场景文件本身的结构/口径/文本校验（不读种子、不读 MANIFEST）。"""
    errors: list[str] = []
    scenarios = data.get("scenarios") or []
    positives = [item for item in scenarios if item.get("run")]
    negatives = [item for item in scenarios if not item.get("run")]
    if data.get("protocol_version") != v4.PROTOCOL_VERSION:
        errors.append(f"protocol_version 应为 {v4.PROTOCOL_VERSION}，"
                      f"实际 {data.get('protocol_version')}")
    if data.get("version") != v4.VERSION:
        errors.append(f"version 应为 {v4.VERSION}")
    if data.get("seed") != v4.SEED:
        errors.append(f"seed 应为 {v4.SEED}")
    if data.get("as_of") != v4.AS_OF.isoformat():
        errors.append(f"as_of 应为 {v4.AS_OF.isoformat()}")
    if data.get("scenario_count") != 48 or len(scenarios) != 48:
        errors.append(f"场景总数应为 48，实际 {data.get('scenario_count')}/{len(scenarios)}")
    if len(positives) != 40:
        errors.append(f"正向数 {len(positives)} != 40")
    if len(negatives) != 8:
        errors.append(f"负向数 {len(negatives)} != 8")
    if data.get("deliver_count") != v4.DELIVER_COUNT:
        errors.append(f"deliver_count 应为 {v4.DELIVER_COUNT}")

    expected_keys = [f"V4_{index:02d}" for index in range(1, 49)]
    expected_accounts = [f"TEST_SCENARIO_V4_{index:02d}" for index in range(1, 49)]
    expected_nicknames = [f"V4场景租客{index:02d}" for index in range(1, 49)]
    if [item.get("key") for item in scenarios] != expected_keys:
        errors.append("场景 key 必须按 V4_01..V4_48 顺序排列")
    if [item.get("account") for item in scenarios] != expected_accounts:
        errors.append("场景 account 必须按 TEST_SCENARIO_V4_01..48 顺序排列")
    if [item.get("slot") for item in scenarios] != list(range(1, 49)):
        errors.append("场景 slot 必须按 1..48 顺序排列")
    if [item.get("profile", {}).get("nickname") for item in scenarios] != expected_nicknames:
        errors.append("昵称必须为 V4场景租客01..48 且与 slot 对齐")

    tiers: dict[str, int] = {}
    cells: set[tuple] = set()
    for index, item in enumerate(positives):
        seq = index + 1
        key = item.get("key")
        capacity = item.get("ex_ante_capacity") or {}
        expect = item.get("expect") or {}
        profile = item.get("profile") or {}
        eligible = capacity.get("eligible")
        unbounded = capacity.get("eligible_unbounded")
        tier = capacity.get("tier")
        tiers[tier] = tiers.get(tier, 0) + 1
        cell = (profile.get("store_id"), profile.get("gender"), profile.get("lease_term"))
        if cell in cells:
            errors.append(f"{key} 正向场景重复格子 {cell}")
        cells.add(cell)
        if item.get("deliver_count") != v4.DELIVER_COUNT:
            errors.append(f"{key} deliver_count 非法")
        if expect.get("can_run") is not True or expect.get("blocker") is not None:
            errors.append(f"{key} 正向 expect.can_run/blocker 非法")
        if not isinstance(eligible, int) or eligible < 1:
            errors.append(f"{key} eligible 非法：{eligible!r}")
        if not isinstance(unbounded, int) or not isinstance(eligible, int) \
                or unbounded < eligible:
            errors.append(f"{key} eligible_unbounded 非法：{unbounded!r}")
        if tier == "high" and isinstance(eligible, int) and eligible < 8:
            errors.append(f"{key} 高容量层 eligible<8：{eligible}")
        elif tier == "medium" and isinstance(eligible, int) and not 4 <= eligible <= 7:
            errors.append(f"{key} 中容量层 eligible 越界：{eligible}")
        elif tier == "low" and isinstance(eligible, int) and not 1 <= eligible <= 3:
            errors.append(f"{key} 低容量层 eligible 越界：{eligible}")
        wanted_target = min(v4.DELIVER_COUNT, unbounded) if isinstance(unbounded, int) else None
        if expect.get("target") != wanted_target:
            errors.append(f"{key} expect.target={expect.get('target')!r} "
                          f"应为 min(8, {unbounded})={wanted_target}")
        if expect.get("target_rule") != v4.TARGET_RULE:
            errors.append(f"{key} expect.target_rule 非法：{expect.get('target_rule')!r}")
        intro = profile.get("self_intro") or ""
        expectation = profile.get("roommate_expectation") or ""
        if f"第 {seq} 次" not in intro:
            errors.append(f"{key} self_intro 未使用最终 slot=seq（第 {seq} 次）")
        if f"第 {seq} 次" not in expectation:
            errors.append(f"{key} roommate_expectation 未使用最终 slot=seq（第 {seq} 次）")
        if "。。" in intro or "。。" in expectation:
            errors.append(f"{key} 文本存在重复句号（未规范化）")
        if "V3场景租客" in intro or "V3场景租客" in (profile.get("nickname") or ""):
            errors.append(f"{key} 文本残留 V3 场景昵称/口径")
        for tag in profile.get("interest_tags") or []:
            if tag in v4.PET_TAGS:
                errors.append(f"{key} 兴趣标签未清洗养宠类：{tag}")
        errors.extend(f"{key} {reason}" for reason in _scan_text(item))
    if tiers != TIER_QUOTAS:
        errors.append(f"容量层配额不匹配：{tiers} != {TIER_QUOTAS}")

    moment_negatives = [item for item in negatives
                        if (item.get("expect") or {}).get("blocker") == "moment"]
    intro_negatives = [item for item in negatives
                       if (item.get("expect") or {}).get("blocker") == "intro"]
    if len(moment_negatives) != 4 or len(intro_negatives) != 4:
        errors.append(f"负向 blocker 数量错误：moment {len(moment_negatives)} / "
                      f"intro {len(intro_negatives)}")
    positive_by_key = {item["key"]: item for item in positives}
    source_indexes: list[int] = []
    for item in negatives:
        capacity = item.get("ex_ante_capacity") or {}
        expect = item.get("expect") or {}
        profile = item.get("profile") or {}
        source_key = capacity.get("source_key")
        source = positive_by_key.get(source_key)
        if source is None:
            errors.append(f"{item.get('key')} 负向来源 {source_key!r} 不是正向场景")
            continue
        source_indexes.append(positives.index(source))
        if item.get("deliver_count") != v4.DELIVER_COUNT:
            errors.append(f"{item.get('key')} 负向 deliver_count 非法")
        if expect.get("can_run") is not False:
            errors.append(f"{item.get('key')} 负向 expect.can_run 应为 False")
        seq = item.get("slot")
        expectation = str(profile.get("roommate_expectation") or "")
        if isinstance(seq, int) and f"第 {seq} 次" not in expectation:
            errors.append(f"{item.get('key')} 负向 roommate_expectation 序号与 slot 不一致")
        if "。。" in expectation or "。。" in str(profile.get("self_intro") or ""):
            errors.append(f"{item.get('key')} 负向文本存在重复句号")
        if expect.get("blocker") == "moment":
            if item.get("moments"):
                errors.append(f"{item.get('key')} moment 负向 moments 必须为空")
            if isinstance(seq, int) and f"第 {seq} 次" not in str(profile.get("self_intro") or ""):
                errors.append(f"{item.get('key')} 负向自我介绍序号与 slot 不一致")
        if expect.get("blocker") == "intro" and profile.get("self_intro"):
            errors.append(f"{item.get('key')} intro 负向 self_intro 必须为空")
    if sorted(source_indexes) != sorted(v4.NEGATIVE_SOURCE_INDICES):
        errors.append(f"负向来源索引应固定为 {list(v4.NEGATIVE_SOURCE_INDICES)}，"
                      f"实际 {sorted(source_indexes)}")
    for name, group in (("moment", moment_negatives), ("intro", intro_negatives)):
        genders = {(item.get("profile") or {}).get("gender") for item in group}
        source_tiers = {(item.get("ex_ante_capacity") or {}).get("source_tier")
                        for item in group}
        if len(genders) < 2:
            errors.append(f"{name} 负向未跨性别：{genders}")
        if len(source_tiers) < 2:
            errors.append(f"{name} 负向未跨容量层：{source_tiers}")

    grid = data.get("grid") or {}
    if grid.get("target_rule") != v4.TARGET_RULE:
        errors.append("grid.target_rule 与 expect 口径不一致")
    sources = grid.get("negative_sources") or {}
    if sources.get("indices") != list(v4.NEGATIVE_SOURCE_INDICES):
        errors.append("grid.negative_sources.indices 非法")
    if sources.get("moment") != [item["ex_ante_capacity"]["source_key"]
                                 for item in moment_negatives]:
        errors.append("grid.negative_sources.moment 与实际负向不一致")
    if sources.get("intro") != [item["ex_ante_capacity"]["source_key"]
                                for item in intro_negatives]:
        errors.append("grid.negative_sources.intro 与实际负向不一致")
    return errors


def check_manifest(manifest: dict, data: dict, scenarios_path: Path,
                   repo_root: Path | str = REPO) -> list[str]:
    """MANIFEST 的 sha / 协议 / 池指纹 / supply_additions / labels 状态校验。"""
    errors: list[str] = []
    declared = (manifest.get("scenarios") or {}).get("sha256")
    actual = _sha256_file(scenarios_path)
    if not declared:
        errors.append("MANIFEST 缺少 scenarios.sha256")
    elif declared != actual:
        errors.append(f"scenarios.json 哈希不一致：文件 {actual} != MANIFEST {declared}")
    if not (manifest.get("scenarios") or {}).get("file"):
        errors.append("MANIFEST 缺少 scenarios.file")
    for name, expected in (
        ("version", v4.VERSION),
        ("protocol_version", v4.PROTOCOL_VERSION),
        ("seed", v4.SEED),
        ("as_of", v4.AS_OF.isoformat()),
        ("scenario_count", 48),
        ("positive_count", 40),
        ("negative_count", 8),
        ("deliver_count", v4.DELIVER_COUNT),
    ):
        if manifest.get(name) != expected:
            errors.append(f"MANIFEST.{name}={manifest.get(name)!r} != {expected!r}")
    if manifest.get("scenario_count") != data.get("scenario_count"):
        errors.append("MANIFEST.scenario_count 与场景文件不一致")

    root = Path(repo_root)
    seed_data = seedmod.load_seed(root)
    stats = seedmod.seed_stats(seed_data)
    pool = manifest.get("pool") or {}
    if pool.get("members") != stats["members"]:
        errors.append(f"MANIFEST.pool.members={pool.get('members')} != {stats['members']}")
    if pool.get("approved") != stats["approved"]:
        errors.append(f"MANIFEST.pool.approved={pool.get('approved')} != {stats['approved']}")
    if not pool.get("source") or not str(pool.get("source")).endswith(".sql"):
        errors.append(f"MANIFEST.pool.source 非法：{pool.get('source')!r}")
    base_sha = freeze.base_sql_sha256(root)
    if pool.get("base_sql_sha256") != base_sha:
        errors.append("MANIFEST.pool.base_sql_sha256 与当前 base SQL 不一致")
    digest = freeze.pool_digest(seed_data)
    if pool.get("pool_digest") != digest:
        errors.append("MANIFEST.pool.pool_digest 与当前种子池不一致（候选池被改写？）")
    additions = len(freeze.find_supply_writes(root / "deploy" / "mysql" / "sql" / "eval"))
    if manifest.get("supply_additions") != additions:
        errors.append(f"MANIFEST.supply_additions={manifest.get('supply_additions')} "
                      f"与实际扫描 {additions} 不一致")
    if additions != 0:
        errors.append(f"eval profile SQL 目录存在 {additions} 条供给写语句（必须为 0）")
    return errors


def check_labels(labels_path: Path, manifest: dict, data: dict,
                 repo_root: Path | str = REPO) -> list[str]:
    """labels 状态与（若已生成）labels.json schema/覆盖校验。"""
    errors: list[str] = []
    labels_block = manifest.get("labels") or {}
    status = labels_block.get("status")
    if not labels_path.is_file():
        if status != "pending":
            errors.append(f"没有 labels.json 时 MANIFEST.labels.status 应为 pending，"
                          f"实际 {status!r}")
        if not labels_block.get("method"):
            errors.append("MANIFEST.labels.method 缺失")
        return errors
    if status != "ready":
        errors.append(f"labels.json 已生成但 MANIFEST.labels.status={status!r}，应为 ready")
        return errors
    import build_v4_labels  # 延迟导入：只在 labels 存在时需要

    return build_v4_labels.check_labels_file(labels_path, data, manifest, repo_root)


def check(base: Path | str | None = None, repo_root: Path | str = REPO) -> list[str]:
    """v4 冻结目录的完整守卫；返回错误清单（空 = 通过）。"""
    base_dir = Path(base) if base else BASE
    root = Path(repo_root)
    scenarios_path = base_dir / SCENARIOS_FILE
    manifest_path = base_dir / MANIFEST_FILE
    missing = [name for name, path in ((SCENARIOS_FILE, scenarios_path),
                                       (MANIFEST_FILE, manifest_path))
               if not path.is_file()]
    if missing:
        return [f"缺少 v4 冻结文件：{missing}（目录 {base_dir}）"]
    try:
        data = _read_json(scenarios_path)
        manifest = _read_json(manifest_path)
    except json.JSONDecodeError as error:
        return [f"冻结文件不是合法 JSON：{error}"]
    errors = check_scenarios(data)
    errors.extend(check_manifest(manifest, data, scenarios_path, root))
    errors.extend(check_labels(base_dir / LABELS_FILE, manifest, data, root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v4 场景/标签冻结守卫")
    parser.add_argument("--frozen-dir", type=Path, default=None, help="冻结目录（测试用）")
    args = parser.parse_args(argv)
    errors = check(args.frozen_dir, REPO)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print("[OK] v4 冻结守卫通过：scenarios sha/协议/40+8/层配额/target/文本自洽/"
          "负向覆盖/pool 指纹/labels 状态")
    return 0


if __name__ == "__main__":
    sys.exit(main())
