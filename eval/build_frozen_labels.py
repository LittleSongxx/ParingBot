#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用离线种子 + 规则生成 v3 冻结标签，并写 MANIFEST 指纹。

标签不是人工金标，是「离线启发式 gold」，用途只有一个：给交付排序/命中率
提供一个冻结的、可复现的参照。它由 v3 场景 + 仓库种子 SQL + 固定规则算出，
与线上数据库、模型输出无关；一旦写入就不允许 CI 自动重算（check_freeze 守护）。

heuristic 打分（协议 v3）：
  门店 3 / 同片区 1、作息 2、预算 2、年龄 1、整洁度 1、
  租期档差 0 → 2 / 档差 1 → 1、兴趣重合 min(2, N)。
每个正向场景取分数最高的前 8 位（同分按 member id 升序），即 gold_ids。

用法：
  python3 eval/build_frozen_labels.py            # 生成并写 labels.json + MANIFEST.json
  python3 eval/build_frozen_labels.py --verify   # 重算标签并比对 MANIFEST 里的 sha256
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from lib import rules, seed as seedmod  # noqa: E402

METHOD = "heuristic-offline-v1"
LABEL_NOTE = (
    "离线启发式 gold（非人工金标）：由 v3 场景 + 仓库种子 SQL + 固定权重算出，"
    "只用于排序/命中率参照；禁止在 CI 中自动重算，变更需升 protocol_version 并人工审阅"
)
WEIGHTS = {
    "store_same": 3,
    "store_area": 1,
    "schedule": 2,
    "budget": 2,
    "age": 1,
    "tidiness": 1,
    "lease_gap_0": 2,
    "lease_gap_1": 1,
    "interest_cap": 2,
}
TOP_K = 8
LABELS_FILE = "labels.json"
MANIFEST_FILE = "MANIFEST.json"
SCENARIOS_FILE = "scenarios.json"


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _interesting(tags) -> set:
    return {str(tag).strip() for tag in (tags or []) if str(tag).strip()}


def heuristic_score(applicant, applicant_preference, candidate,
                    as_of: date | None = None) -> int:
    """离线启发式适配分：只看白盒信号，权重固定、可解释。"""
    score = 0
    if candidate.store_id is not None and candidate.store_id == applicant.store_id:
        score += WEIGHTS["store_same"]
    elif rules.area_of(candidate.store_id) == rules.area_of(applicant.store_id):
        score += WEIGHTS["store_area"]
    accepted = set(applicant_preference.schedule_accept or [])
    if candidate.schedule_type and candidate.schedule_type in accepted:
        score += WEIGHTS["schedule"]
    if (candidate.rent_budget is not None
            and applicant_preference.budget_min is not None
            and applicant_preference.budget_max is not None
            and applicant_preference.budget_min <= candidate.rent_budget <= applicant_preference.budget_max):
        score += WEIGHTS["budget"]
    age = rules.age_of(candidate.birth_date, as_of)
    if (age is not None and applicant_preference.age_min is not None
            and applicant_preference.age_max is not None
            and applicant_preference.age_min <= age <= applicant_preference.age_max):
        score += WEIGHTS["age"]
    if (candidate.tidiness and applicant_preference.tidiness_min
            and candidate.tidiness in rules.TIDINESS_LEVELS
            and applicant_preference.tidiness_min in rules.TIDINESS_LEVELS
            and rules.TIDINESS_LEVELS.index(candidate.tidiness)
            >= rules.TIDINESS_LEVELS.index(applicant_preference.tidiness_min)):
        score += WEIGHTS["tidiness"]
    gap = rules.term_gap(applicant.lease_term, candidate.lease_term)
    if gap == 0:
        score += WEIGHTS["lease_gap_0"]
    elif gap == 1:
        score += WEIGHTS["lease_gap_1"]
    shared = _interesting(applicant.interest_tags) & _interesting(candidate.interest_tags)
    score += min(WEIGHTS["interest_cap"], len(shared))
    return score


def label_for_scenario(scenario: dict, pool, preferences, as_of: date) -> dict:
    """单个正向场景的冻结标签：硬可匹配全集 + 启发式排序 + gold 前 8。"""
    applicant = seedmod.member_from_payload(scenario["profile"])
    applicant_preference = seedmod.preference_from_payload(scenario["preference"])
    ranked_full = []
    for candidate in pool:
        candidate_preference = preferences.get(candidate.id)
        if candidate_preference is None:
            continue
        if not rules.is_hard_eligible(applicant, applicant_preference,
                                      candidate, candidate_preference, as_of):
            continue
        ranked_full.append({
            "id": candidate.id,
            "score": heuristic_score(applicant, applicant_preference, candidate, as_of),
        })
    ranked_full.sort(key=lambda item: (-item["score"], item["id"]))
    gold = ranked_full[:TOP_K]
    return {
        "username": scenario["account"],
        "key": scenario["key"],
        "case": "positive",
        "gold_ids": [item["id"] for item in gold],
        "ranked": ranked_full,
        "ranked_total": len(ranked_full),
        "hard_eligible": len(ranked_full),
        "ex_ante_capacity": scenario.get("ex_ante_capacity"),
    }


def build_labels(scenarios_data: dict, repo_root: Path | str = REPO) -> dict:
    """按场景文件生成完整 labels 字典（纯函数，不写文件）。"""
    root = Path(repo_root)
    as_of = date.fromisoformat(scenarios_data["as_of"])
    seed_data = seedmod.load_seed(root)
    pool = seedmod.approved_candidates(seed_data)
    preferences = seed_data.preferences
    labels = []
    for scenario in scenarios_data.get("scenarios", []):
        if not scenario.get("run"):
            continue
        labels.append(label_for_scenario(scenario, pool, preferences, as_of))
    return {
        "version": scenarios_data.get("version", "v3"),
        "protocol_version": scenarios_data.get("protocol_version"),
        "method": METHOD,
        "note": LABEL_NOTE,
        "seed": scenarios_data.get("seed"),
        "as_of": scenarios_data["as_of"],
        "top_k": TOP_K,
        "weights": dict(WEIGHTS),
        "labels": labels,
    }


def dump_labels(labels: dict) -> str:
    """确定性序列化（无时间戳；重复构建字节一致）。"""
    return json.dumps(labels, ensure_ascii=False, indent=2) + "\n"


def _pool_stats(seed_data, repo_root: Path) -> dict:
    stats = seedmod.seed_stats(seed_data)
    source = Path(stats.get("source") or "")
    try:
        stats["source"] = str(source.resolve().relative_to(Path(repo_root).resolve()))
    except (ValueError, OSError):
        stats["source"] = str(source)
    return stats


def _manifest_file(base: Path, name: str, repo_root: Path) -> str:
    """MANIFEST 里记录仓库相对路径，方便 CI 直接按它定位文件；临时目录回退文件名。"""
    try:
        return (base / name).resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return name


def build_manifest(scenarios_bytes: bytes, labels_bytes: bytes, scenario_file: str,
                   labels_file: str, scenarios_data: dict, repo_root: Path | str = REPO,
                   created_at: str | None = None) -> dict:
    """MANIFEST：冻结文件的 sha256、协议版本、种子与候选池统计。"""
    root = Path(repo_root)
    seed_data = seedmod.load_seed(root)
    return {
        "version": scenarios_data.get("version", "v3"),
        "protocol_version": scenarios_data.get("protocol_version"),
        "seed": scenarios_data.get("seed"),
        "as_of": scenarios_data.get("as_of"),
        "supply_additions": 0,
        "scenario_count": scenarios_data.get("scenario_count"),
        "positive_count": scenarios_data.get("positive_count"),
        "negative_count": scenarios_data.get("negative_count"),
        "scenarios": {"file": scenario_file, "sha256": _sha256(scenarios_bytes)},
        "labels": {"file": labels_file, "sha256": _sha256(labels_bytes)},
        "pool": _pool_stats(seed_data, root),
        "label_rule": {"method": METHOD, "top_k": TOP_K, "weights": dict(WEIGHTS)},
        "created_at": created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def dump_manifest(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def generate(scenarios_dir: Path | str | None = None, repo_root: Path | str = REPO,
             write: bool = True) -> dict:
    """生成 labels 与 MANIFEST；write=False 时只返回内存结果。"""
    base = Path(scenarios_dir) if scenarios_dir else (EVAL_DIR / "frozen" / "v3")
    scenarios_path = base / SCENARIOS_FILE
    scenarios_bytes = scenarios_path.read_bytes()
    scenarios_data = json.loads(scenarios_bytes.decode("utf-8"))
    labels = build_labels(scenarios_data, repo_root)
    labels_text = dump_labels(labels)
    labels_bytes = labels_text.encode("utf-8")
    manifest = build_manifest(
        scenarios_bytes, labels_bytes,
        _manifest_file(base, SCENARIOS_FILE, Path(repo_root)),
        _manifest_file(base, LABELS_FILE, Path(repo_root)),
        scenarios_data, repo_root)
    if write:
        (base / LABELS_FILE).write_text(labels_text, encoding="utf-8")
        (base / MANIFEST_FILE).write_text(dump_manifest(manifest), encoding="utf-8")
    return {"scenarios_path": scenarios_path, "labels": labels, "labels_text": labels_text,
            "manifest": manifest, "labels_bytes": labels_bytes,
            "scenarios_bytes": scenarios_bytes}


def verify(scenarios_dir: Path | str | None = None, repo_root: Path | str = REPO) -> int:
    """重算标签并比对 MANIFEST；任何不一致都返回非 0（fail-closed）。"""
    base = Path(scenarios_dir) if scenarios_dir else (EVAL_DIR / "frozen" / "v3")
    errors: list[str] = []
    scenarios_path = base / SCENARIOS_FILE
    labels_path = base / LABELS_FILE
    manifest_path = base / MANIFEST_FILE
    for path in (scenarios_path, labels_path, manifest_path):
        if not path.is_file():
            print(f"[FAIL] 缺少冻结文件：{path}")
            return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenarios_bytes = scenarios_path.read_bytes()
    labels_bytes = labels_path.read_bytes()
    actual_scenarios = _sha256(scenarios_bytes)
    actual_labels = _sha256(labels_bytes)
    declared_scenarios = (manifest.get("scenarios") or {}).get("sha256")
    declared_labels = (manifest.get("labels") or {}).get("sha256")
    if actual_scenarios != declared_scenarios:
        errors.append(f"scenarios.json 哈希不一致：文件 {actual_scenarios} != MANIFEST {declared_scenarios}")
    if actual_labels != declared_labels:
        errors.append(f"labels.json 哈希不一致：文件 {actual_labels} != MANIFEST {declared_labels}")
    # 重算标签：种子/规则/场景任一漂移都会让哈希对不上
    result = generate(base, repo_root, write=False)
    recomputed = _sha256(result["labels_bytes"])
    if recomputed != declared_labels:
        errors.append(f"重算标签哈希不一致：重算 {recomputed} != MANIFEST {declared_labels}"
                      f"（种子 SQL 或规则口径漂移）")
    if result["labels_text"].encode("utf-8") != labels_bytes:
        errors.append("labels.json 内容与重算结果不一致（文件被手改或构建非确定性）")
    if errors:
        for item in errors:
            print(f"[FAIL] {item}")
        return 1
    print(f"[OK] 冻结文件校验通过：scenarios {actual_scenarios[:12]}… / labels {actual_labels[:12]}…")
    print(f"[OK] 池统计：approved={manifest.get('pool', {}).get('approved')}，"
          f"labels={len(result['labels']['labels'])} 个场景")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 v3 冻结标签与 MANIFEST")
    parser.add_argument("--verify", action="store_true", help="重算并比对 MANIFEST 哈希")
    parser.add_argument("--scenarios-dir", type=Path, default=None,
                        help="冻结目录（默认 eval/frozen/v3）")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        return verify(args.scenarios_dir)
    result = generate(args.scenarios_dir, write=True)
    base = Path(args.scenarios_dir) if args.scenarios_dir else (EVAL_DIR / "frozen" / "v3")
    if args.quiet:
        print(base / LABELS_FILE)
        return 0
    labels = result["labels"]
    print(f"写入 {base / LABELS_FILE} 与 {base / MANIFEST_FILE}")
    print(f"标签 {len(labels['labels'])} 个场景，method={labels['method']}，seed={labels['seed']}")
    for item in labels["labels"]:
        print(f"  {item['key']} hard_eligible={item['hard_eligible']} "
              f"gold={item['gold_ids'][:8]}")
    print(f"MANIFEST：scenarios={result['manifest']['scenarios']['sha256'][:12]}… "
          f"labels={result['manifest']['labels']['sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())