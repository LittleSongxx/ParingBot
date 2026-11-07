#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计双人人工作业的 Cohen's kappa，并把分歧回填到裁决表。

角色边界（quality-v1）：人工只做“校准 / 裁决 / 验收”。本脚本只回答“两位评者
是否一致到可以当人工真值”（E3 门禁），不替代 judge、不产出质量结论。

输入（build_calibration.py 的 --out-dir）：
  blind_set.json、key.json、annotations_annotator_a.csv、annotations_annotator_b.csv

输出：
  agreement.json（默认写回 --dir）
    {n, agreement, kappa, by_stratum, usable, reasons, unfilled, disagreements, threshold}
  adjudication.csv（覆盖写：分歧行；保留人工已填的 final_winner/notes）

退出码：0 = 双人标注完整且 kappa >= quality_spec.JUDGE_GATES["human_kappa_min"]；
        1 = 未完成/不一致/文件缺失。

用法：
  python eval/human_eval/agreement.py --dir eval/human_eval/calibration \
      --out eval/human_eval/calibration/agreement.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:  # 支持 `python eval/human_eval/agreement.py` 直接运行
    sys.path.insert(0, str(EVAL))

from lib.stats import agreement_rate, cohen_kappa  # noqa: E402
from quality_spec import JUDGE_GATES  # noqa: E402

WINNERS = ("A", "B", "tie")
ANNOTATION_COLUMNS = ("pair_id", "winner", "confidence", "notes")
ADJUDICATION_COLUMNS = ("pair_id", "annotator_a", "annotator_b", "final_winner", "notes")
ANNOTATION_FILES = {"annotator_a": "annotations_annotator_a.csv",
                    "annotator_b": "annotations_annotator_b.csv"}


def read_annotations(path: Path) -> dict[str, dict]:
    """读标注 CSV；返回 pair_id → 原始行（保留 winner/confidence/notes）。"""
    rows: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            pair_id = str(row.get("pair_id") or "").strip()
            if not pair_id:
                continue
            rows[pair_id] = {
                "pair_id": pair_id,
                "winner": str(row.get("winner") or "").strip(),
                "confidence": str(row.get("confidence") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
            }
    return rows


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_key(directory: Path) -> dict[str, dict]:
    """读 key.json；兼容扁平 dict 与 quality_pairwise 的 {"key": {...}} 包装。"""
    path = Path(directory) / "key.json"
    if not path.exists():
        return {}
    raw = read_json(path)
    if isinstance(raw, dict) and isinstance(raw.get("key"), dict):
        raw = raw["key"]
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    return {}


def load_blind(directory: Path) -> tuple[list[str], dict[str, str]]:
    """读 blind_set.json；返回 (按文件顺序的 pair_id 列表, pair_id → stratum)。"""
    path = Path(directory) / "blind_set.json"
    if not path.exists():
        return [], {}
    raw = read_json(path)
    pairs = raw.get("pairs") if isinstance(raw, dict) else raw
    if not isinstance(pairs, list):
        return [], {}
    ordered: list[str] = []
    strata: dict[str, str] = {}
    for row in pairs:
        if not isinstance(row, dict) or row.get("pair_id") is None:
            continue
        pair_id = str(row["pair_id"])
        ordered.append(pair_id)
        strata[pair_id] = str(row.get("stratum") or "unknown")
    return ordered, strata


def read_adjudication(path: Path) -> dict[str, dict]:
    """读已有裁决表（保留人工填写的 final_winner/notes）。"""
    rows: dict[str, dict] = {}
    path = Path(path)
    if not path.exists():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            pair_id = str(row.get("pair_id") or "").strip()
            if not pair_id:
                continue
            rows[pair_id] = {
                "pair_id": pair_id,
                "annotator_a": str(row.get("annotator_a") or "").strip(),
                "annotator_b": str(row.get("annotator_b") or "").strip(),
                "final_winner": str(row.get("final_winner") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
            }
    return rows


def _stratum_stats(items: list[dict]) -> dict:
    """单档一致率/kappa；n<2 时 kappa 记 None（样本不足，不硬算）。"""
    n = len(items)
    result = {"n": n,
              "agreement": round(agreement_rate([item["annotator_a"] for item in items],
                                                [item["annotator_b"] for item in items]), 4),
              "kappa": None}
    if n >= 2:
        result["kappa"] = round(cohen_kappa([item["annotator_a"] for item in items],
                                           [item["annotator_b"] for item in items]), 4)
    return result


def analyze(directory: Path) -> dict:
    """计算双人一致率/kappa/分歧，并回填裁决表。"""
    directory = Path(directory)
    missing = [filename for filename in ANNOTATION_FILES.values()
               if not (directory / filename).exists()]
    if missing:
        raise FileNotFoundError(f"缺少标注文件：{', '.join(missing)}（目录 {directory}）")
    annotations = {name: read_annotations(directory / filename)
                   for name, filename in ANNOTATION_FILES.items()}

    blind_order, strata = load_blind(directory)
    key = load_key(directory)
    declared = list(blind_order)
    if not declared:
        declared = sorted(set(key) | set(annotations["annotator_a"])
                          | set(annotations["annotator_b"]))
    known = set(declared)
    extra = sorted((set(annotations["annotator_a"]) | set(annotations["annotator_b"])) - known)
    declared.extend(extra)

    invalid: list[dict] = []
    valid_rows: list[dict] = []
    unfilled: list[str] = []
    for pair_id in declared:
        values = {}
        invalid_here = False
        for name in ("annotator_a", "annotator_b"):
            winner = annotations[name].get(pair_id, {}).get("winner", "")
            values[name] = winner
            if winner and winner not in WINNERS:
                invalid.append({"pair_id": pair_id, "annotator": name, "winner": winner})
                invalid_here = True
        if invalid_here:
            continue
        if all(values[name] in WINNERS for name in ("annotator_a", "annotator_b")):
            valid_rows.append({"pair_id": pair_id,
                               "stratum": strata.get(pair_id, "unknown"),
                               "annotator_a": values["annotator_a"],
                               "annotator_b": values["annotator_b"]})
        else:
            unfilled.append(pair_id)

    kappa_min = float(JUDGE_GATES["human_kappa_min"])
    if valid_rows:
        agreement_value = round(agreement_rate([row["annotator_a"] for row in valid_rows],
                                               [row["annotator_b"] for row in valid_rows]), 4)
        kappa_value = round(cohen_kappa([row["annotator_a"] for row in valid_rows],
                                        [row["annotator_b"] for row in valid_rows]), 4)
    else:
        agreement_value = None
        kappa_value = None

    by_stratum: dict[str, dict] = {}
    for row in valid_rows:
        by_stratum.setdefault(row["stratum"], []).append(row)
    by_stratum = {stratum: _stratum_stats(items)
                  for stratum, items in sorted(by_stratum.items())}

    disagreements = [{"pair_id": row["pair_id"], "stratum": row["stratum"],
                      "annotator_a": row["annotator_a"], "annotator_b": row["annotator_b"]}
                     for row in valid_rows if row["annotator_a"] != row["annotator_b"]]

    adjudication_path = directory / "adjudication.csv"
    existing = read_adjudication(adjudication_path)
    adjudication_rows: list[dict] = []
    valid_ids = {row["pair_id"] for row in valid_rows}
    for row in sorted(valid_rows, key=lambda item: str(item["pair_id"])):
        pair_id = row["pair_id"]
        previous = existing.get(pair_id, {})
        agreed = row["annotator_a"] == row["annotator_b"]
        auto_winner = row["annotator_a"] if agreed else ""
        adjudication_rows.append({
            "pair_id": pair_id,
            "annotator_a": row["annotator_a"],
            "annotator_b": row["annotator_b"],
            "final_winner": previous.get("final_winner") or auto_winner,
            "notes": previous.get("notes")
                     or ("双人一致自动裁决" if agreed
                         else f"分歧待裁决（a={row['annotator_a']}，b={row['annotator_b']}）"),
        })
    # 保留已人工裁决、但当前不在有效标注里的历史行（不能因重跑丢裁决记录）。
    for pair_id, row in sorted(existing.items()):
        if pair_id in valid_ids:
            continue
        if row.get("final_winner") or row.get("notes"):
            adjudication_rows.append(row)
    adjudication_rows.sort(key=lambda row: str(row["pair_id"]))
    _write_csv(adjudication_path, ADJUDICATION_COLUMNS, adjudication_rows)
    pending = [row for row in adjudication_rows if not row.get("final_winner")]

    reasons: list[str] = []
    if invalid:
        reasons.append(f"{len(invalid)} 个标注值不在 A/B/tie（{', '.join(item['pair_id'] for item in invalid[:5])}）")
    if unfilled:
        reasons.append(f"{len(unfilled)} 对未完成双人标注")
    if not valid_rows:
        reasons.append("没有可计算的双人标注样本")
    elif kappa_value is not None and kappa_value < kappa_min:
        reasons.append(f"Cohen kappa={kappa_value:.3f} < {kappa_min}")
    usable = not reasons
    result = {
        "n": len(valid_rows),
        "declared": len(declared),
        "agreement": agreement_value,
        "kappa": kappa_value,
        "by_stratum": by_stratum,
        "disagreements": disagreements,
        "unfilled": unfilled,
        "invalid": invalid,
        "usable": usable,
        "reasons": reasons,
        "threshold": {"key": "human_kappa_min", "value": kappa_min,
                      "source": "quality_spec.JUDGE_GATES"},
        "adjudication": adjudication_path.name,
        "adjudicated": {"total": len(adjudication_rows),
                        "auto_agreed": len(adjudication_rows) - len(pending),
                        "pending": len(pending)},
        "note": "人工一致性只做校准/裁决门禁（E3）；kappa<0.6 时 judge 校准与质量结论均不可用。",
    }
    return result


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="计算双人盲评一致率与 Cohen kappa，回填裁决表")
    parser.add_argument("--dir", required=True, type=Path,
                        help="build_calibration.py 的输出目录")
    parser.add_argument("--out", type=Path, default=None,
                        help="agreement.json 路径（默认 <dir>/agreement.json）")
    args = parser.parse_args(argv)
    out_path = args.out or (args.dir / "agreement.json")
    try:
        result = analyze(args.dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("n", "declared", "agreement", "kappa", "usable", "reasons")},
                     ensure_ascii=False))
    return 0 if result["usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
