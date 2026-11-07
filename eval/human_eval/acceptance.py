#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工验收抽样与签核：从最终质量报告里分层抽 15% 对做人工复核。

角色边界（quality-v1）：人工只做“校准 / 裁决 / 验收”。本脚本不产生质量结论，
只负责：
1. 从最终质量报告（优先 report.pairs，缺失时退回校准集 key.json）按档位分层
   抽 rate（默认 quality_spec.SAMPLE_FLOORS["human_acceptance_rate"]=15%）；
   输出 acceptance.csv（pair_id,stratum,human_winner,notes；human_winner 待填）。
2. `--check`：校验验收表填写完整、与 judge 胜率方向的一致率（Cohen kappa），
   写 signoff.json {usable, n, agreement, kappa, reasons}。
   阈值取 quality_spec.JUDGE_GATES["human_kappa_min"]（唯一口径源，不在这里另写数字）。

human_winner 词表：A/B/tie（盲评侧）或 delivered/control/tie（已折算方向）；
A/B 需用 --key 里的 delivered_side 折算成 delivered/control 才能和 judge 对方向。

用法：
  python eval/human_eval/acceptance.py \
      --report quality-report.json --key eval/human_eval/calibration/key.json \
      --out eval/human_eval/calibration/acceptance.csv --rate 0.15 --seed 20261106
  python eval/human_eval/acceptance.py \
      --report quality-report.json --key eval/human_eval/calibration/key.json \
      --check eval/human_eval/calibration/acceptance.csv \
      --json eval/human_eval/calibration/signoff.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:  # 支持 `python eval/human_eval/acceptance.py` 直接运行
    sys.path.insert(0, str(EVAL))

from lib.stats import cohen_kappa  # noqa: E402
from quality_spec import JUDGE_GATES, SAMPLE_FLOORS  # noqa: E402

DEFAULT_SEED = 20261106
ACCEPTANCE_COLUMNS = ("pair_id", "stratum", "human_winner", "notes")


def _derive_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}::{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_key(path: Path) -> dict[str, dict]:
    """读 key.json；兼容扁平 dict / {"key": {...}} / list-of-dicts 三种形态。"""
    raw = read_json(path)
    if isinstance(raw, dict) and isinstance(raw.get("key"), dict):
        raw = raw["key"]
    mapping: dict[str, dict] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                mapping[str(key)] = value
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("pair_id") is not None:
                mapping[str(item["pair_id"])] = item
    else:
        raise ValueError(f"key 格式不支持：{path}")
    return mapping


def _map_winner(value, delivered_side) -> str | None:
    """把 A/B/delivered/control/tie 统一折算成 delivered/control/tie。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in ("delivered", "control", "tie"):
        return lower
    upper = text.upper()
    if upper in ("A", "B"):
        side = str(delivered_side or "").strip().upper()
        if side in ("A", "B"):
            return "delivered" if upper == side else "control"
    return None


def _verdict_direction(verdict, index: int, row_side) -> str | None:
    """解析单条 verdict：优先用显式 delivered_side，否则按双向约定推。

    quality_pairwise 的约定：verdicts[0] 未交换（A=delivered），
    verdicts[1] 已交换（A=control）；两条都指 delivered 才算 delivered 胜。
    """
    if isinstance(verdict, dict):
        value = verdict.get("winner", verdict.get("judge_winner"))
        side = verdict.get("delivered_side") or row_side
    else:
        value = verdict
        side = row_side
    mapped = _map_winner(value, side)
    if mapped is not None:
        return mapped
    upper = str(value or "").strip().upper()
    if upper in ("A", "B"):
        delivered_on = "A" if index == 0 else "B"  # 第二条已交换 A/B
        return "delivered" if upper == delivered_on else "control"
    if str(value or "").strip().lower() == "tie":
        return "tie"
    return None


def judge_direction(row) -> str | None:
    """从质量报告的单对明细里提取 judge 的胜率方向（delivered/control/tie）。

    兼容 quality_pairwise / judge_calibration 的多种明细形态：
    winner 字段、delivered_win/control_win/tie 布尔、verdicts（双向交换）列表。
    """
    if not isinstance(row, dict):
        return None
    side = row.get("delivered_side")
    for field in ("judge_winner", "final_winner", "winner", "direction", "delivered_winner"):
        mapped = _map_winner(row.get(field), side)
        if mapped is not None:
            return mapped
    for field, outcome in (("delivered_win", "delivered"), ("control_win", "control"),
                           ("tie", "tie")):
        if row.get(field) is True:
            return outcome
    verdicts = row.get("verdicts")
    if isinstance(verdicts, list) and verdicts:
        outcomes = [_verdict_direction(verdict, index, side)
                    for index, verdict in enumerate(verdicts)]
        if outcomes and all(item is not None for item in outcomes):
            if len(set(outcomes)) == 1:  # 正反两次指向同一方才算稳定的方向
                return outcomes[0]
    return None


def _find_pairs(container, depth: int = 0):
    """在报告里递归找成对明细：兼容顶层 pairs 与 metrics.match_quality.pairs。"""
    if depth > 4:
        return []
    if isinstance(container, dict):
        rows = container.get("pairs")
        if isinstance(rows, list) and rows:
            return rows
        for value in container.values():
            found = _find_pairs(value, depth + 1)
            if found:
                return found
    return []


def extract_report_pairs(report) -> list[dict]:
    """从质量报告里取单对明细；容忍 {metric: {pairs: [...]}} 的嵌套形态。"""
    rows = _find_pairs(report)
    pairs: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pair_id = row.get("pair_id", row.get("id"))
        if pair_id is None:
            continue
        pairs.append({"pair_id": str(pair_id),
                      "stratum": str(row.get("stratum") or "unknown"),
                      "judge_direction": judge_direction(row)})
    return pairs


def sampling_pool(report, key: dict[str, dict]) -> list[dict]:
    """抽样池：优先质量报告明细，报告没有明细时退回校准集 key。"""
    pool = extract_report_pairs(report)
    if not pool:
        pool = [{"pair_id": pair_id,
                 "stratum": str(entry.get("stratum") or "unknown"),
                 "judge_direction": None}
                for pair_id, entry in sorted(key.items())]
    deduped: dict[str, dict] = {}
    for item in pool:
        pair_id = item["pair_id"]
        if pair_id in deduped:
            continue
        if item["stratum"] == "unknown" and pair_id in key:
            item["stratum"] = str(key[pair_id].get("stratum") or "unknown")
        deduped[pair_id] = item
    return [deduped[pair_id] for pair_id in sorted(deduped)]


def sample_acceptance(pool: list[dict], rate: float = None,
                      seed: int = DEFAULT_SEED) -> list[dict]:
    """按档位分层抽 rate 比例（每档至少 1 对），返回待填验收行。"""
    if rate is None:
        rate = float(SAMPLE_FLOORS["human_acceptance_rate"])
    if not 0 < float(rate) <= 1:
        raise ValueError(f"--rate 必须在 (0,1]：{rate}")
    if not pool:
        raise ValueError("没有可抽样的 pair（质量报告无 pairs 且 key 为空）")
    grouped: dict[str, list[str]] = {}
    for item in pool:
        grouped.setdefault(item["stratum"], []).append(item["pair_id"])
    sampled: list[dict] = []
    for stratum in sorted(grouped):
        pair_ids = sorted(set(grouped[stratum]))
        take = min(len(pair_ids), max(1, int(math.ceil(float(rate) * len(pair_ids)))))
        rng = random.Random(_derive_seed(seed, f"acceptance::{stratum}"))
        chosen = sorted(rng.sample(pair_ids, take))
        for pair_id in chosen:
            sampled.append({"pair_id": pair_id, "stratum": stratum,
                            "human_winner": "", "notes": ""})
    return sampled


def write_acceptance(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ACCEPTANCE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in ACCEPTANCE_COLUMNS})


def read_acceptance(path: Path) -> list[dict]:
    rows: list[dict] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in ("pair_id", "stratum", "human_winner")
                   if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"验收表缺少列：{', '.join(missing)}")
        for row in reader:
            rows.append({column: str(row.get(column) or "").strip()
                         for column in ACCEPTANCE_COLUMNS})
    return rows


def check_acceptance(acceptance_path: Path, report, key: dict[str, dict]) -> dict:
    """校验验收表完整性，并算人工 vs judge 方向一致率/kappa，给出可用性签核。"""
    rows = read_acceptance(acceptance_path)
    report_pairs = {item["pair_id"]: item for item in extract_report_pairs(report)}
    missing: list[str] = []
    invalid: list[dict] = []
    unmapped: list[str] = []
    mismatches: list[dict] = []
    comparable: list[str] = []
    human_labels: list[str] = []
    judge_labels: list[str] = []
    for row in rows:
        pair_id = row["pair_id"]
        if not pair_id:
            invalid.append({"pair_id": "", "reason": "缺少 pair_id"})
            continue
        raw = row["human_winner"]
        if not raw:
            missing.append(pair_id)
            continue
        human = _map_winner(raw, (key.get(pair_id) or {}).get("delivered_side"))
        if human is None:
            invalid.append({"pair_id": pair_id, "human_winner": raw})
            continue
        judge = (report_pairs.get(pair_id) or {}).get("judge_direction")
        if judge is None:
            unmapped.append(pair_id)
            continue
        comparable.append(pair_id)
        human_labels.append(human)
        judge_labels.append(judge)
        if human != judge:
            mismatches.append({"pair_id": pair_id, "human": human, "judge": judge})

    agreement_value = (round(sum(1 for left, right in zip(human_labels, judge_labels) if left == right)
                             / len(comparable), 4) if comparable else None)
    kappa_value = (round(cohen_kappa(human_labels, judge_labels), 4)
                   if len(comparable) >= 2 else None)
    threshold = float(JUDGE_GATES["human_kappa_min"])
    reasons: list[str] = []
    if not rows:
        reasons.append("验收表为空")
    if missing:
        reasons.append(f"{len(missing)} 行未填 human_winner：{', '.join(missing[:5])}")
    if invalid:
        reasons.append(f"{len(invalid)} 行取值非法（仅允许 A/B/tie/delivered/control）")
    if unmapped:
        reasons.append(f"{len(unmapped)} 行缺少 judge 方向（报告明细或 key 不全）：{', '.join(unmapped[:5])}")
    if not comparable:
        reasons.append("没有可核对的样本")
    elif kappa_value is None:
        reasons.append("可核对样本不足（<2）")
    elif kappa_value < threshold:
        reasons.append(f"人工-judge 方向 Cohen kappa={kappa_value:.3f} < {threshold}")
    usable = not reasons
    result = {
        "usable": usable,
        "n": len(comparable),
        "rows": len(rows),
        "agreement": agreement_value,
        "kappa": kappa_value,
        "threshold": {"key": "human_kappa_min", "value": threshold,
                      "source": "quality_spec.JUDGE_GATES"},
        "reasons": reasons,
        "missing": missing,
        "invalid": invalid,
        "unmapped": unmapped,
        "mismatches": mismatches,
        "strata": dict(sorted(Counter(row["stratum"] for row in rows).items())),
        "note": "人工验收只核对 judge 方向是否可信（E3 抽检），不产生新的质量结论。",
    }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="人工验收：分层抽 15% 并核对 judge 方向")
    parser.add_argument("--report", required=True, type=Path, help="最终质量报告 JSON")
    parser.add_argument("--key", required=True, type=Path,
                        help="build_calibration.py 的 key.json（A/B → delivered 折算）")
    parser.add_argument("--out", type=Path, default=None,
                        help="验收表输出路径（抽样模式必填）")
    parser.add_argument("--rate", type=float,
                        default=float(SAMPLE_FLOORS["human_acceptance_rate"]),
                        help="抽样比例（默认 quality_spec.SAMPLE_FLOORS）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="抽样种子")
    parser.add_argument("--check", type=Path, default=None,
                        help="已填写的验收表；给出后进入签核模式")
    parser.add_argument("--json", type=Path, default=None,
                        help="signoff.json 路径（默认与验收表同目录 signoff.json）")
    args = parser.parse_args(argv)

    try:
        report = read_json(args.report)
        key = load_key(args.key)
        if args.check is not None:
            result = check_acceptance(args.check, report, key)
            json_path = args.json or (args.check.parent / "signoff.json")
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
            printable = {name: result[name] for name in
                         ("usable", "n", "rows", "agreement", "kappa", "threshold", "reasons")}
            print(json.dumps(printable, ensure_ascii=False))
            return 0 if result["usable"] else 1
        if args.out is None:
            parser.error("抽样模式需要 --out（或用 --check 进入签核模式）")
        pool = sampling_pool(report, key)
        rows = sample_acceptance(pool, rate=args.rate, seed=args.seed)
        write_acceptance(args.out, rows)
        print(json.dumps({"out": str(args.out), "n": len(rows), "rate": args.rate,
                          "seed": args.seed,
                          "strata": dict(sorted(Counter(row["stratum"] for row in rows).items()))},
                         ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
