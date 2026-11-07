#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 judge 的成对材料转成人工盲评校准集（双人标注 + 裁决表）。

角色边界（quality-v1）：人工只做“校准 / 裁决 / 验收”三件事；本脚本不产生任何
质量结论，也不修改 judge 材料，只负责：

1. 按档位（near_miss / rejected / random）分层抽样，默认 60/20/20（n=100）；
2. 重新随机化 A/B 顺序（seed 固定、可复现），答案单独封存在 key.json；
3. 校验盲材料不含 delivered/audit_status/screen_score/evidence/rank/*_role 等系统元数据；
4. 输出双人标注表与空裁决表（agreement.py 再把分歧回填进裁决表）。

输入（quality_pairwise.py --emit-materials 的 JSON）：
  {"protocol": str,
   "pairs": [{pair_id, stratum, applicant, candidate_a, candidate_b}],
   "key":   {pair_id: {delivered_side: "A"|"B", delivered_id, control_id, stratum}}}

输出（--out-dir）：
  blind_set.json / key.json / annotations_annotator_a.csv /
  annotations_annotator_b.csv / adjudication.csv

用法：
  python eval/human_eval/build_calibration.py \
      --materials eval/human_eval/calibration/materials.json \
      --out-dir eval/human_eval/calibration --n 100 --seed 20261106
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_SEED = 20261106
DEFAULT_N = 100
DEFAULT_PROTOCOL = "quality-v1-2026-11-06"
HUMAN_PROTOCOL = "human-v1"
DEFAULT_STRATA_WEIGHTS = {"near_miss": 0.60, "rejected": 0.20, "random": 0.20}
ANNOTATION_COLUMNS = ("pair_id", "winner", "confidence", "notes")
ADJUDICATION_COLUMNS = ("pair_id", "annotator_a", "annotator_b", "final_winner", "notes")

# 盲材料里一旦出现这些 key，说明系统结论泄漏（交付/审核/打分/排序/角色）。
FORBIDDEN_BLIND_KEYS = (
    "delivered", "delivered_side", "delivered_id", "control_id", "audit_status",
    "screen_score", "evidence", "rank", "delivered_rank", "screen_rank",
    "reject_code", "reject_reason", "delivered_to_user", "candidate_row_id",
    "found_round", "relax_note", "judge_winner", "winner",
)


def _is_forbidden_key(key: object) -> bool:
    name = str(key)
    return name in FORBIDDEN_BLIND_KEYS or name.endswith("_role")


def _iter_leaks(node, path: str = "$"):
    """深度遍历材料，返回泄漏字段路径（dict/list 均可）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            name = str(key)
            child = f"{path}.{name}"
            if _is_forbidden_key(name):
                yield child
            else:
                yield from _iter_leaks(value, child)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _iter_leaks(value, f"{path}[{index}]")


def blind_material_leaks(payload) -> list[str]:
    """返回盲材料里的系统元数据/角色字段路径；空列表表示安全。"""
    return list(_iter_leaks(payload))


def _derive_seed(seed: int, label: str) -> int:
    """由全局 seed + 标签派生稳定种子（跨进程/跨平台可复现）。"""
    digest = hashlib.sha256(f"{seed}::{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def parse_strata(text: str | None) -> dict[str, int] | None:
    """解析 --strata near_miss=60,rejected=20,random=20。"""
    if text is None:
        return None
    counts: dict[str, int] = {}
    for chunk in re.split(r"[,;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, sep, value = chunk.partition("=")
        name = name.strip()
        if not sep or not name:
            raise ValueError(f"--strata 需要 name=count 形式：{chunk!r}")
        if name in counts:
            raise ValueError(f"--strata 档位重复：{name}")
        try:
            number = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"--strata 的数量必须是整数：{chunk!r}") from exc
        if number < 0:
            raise ValueError(f"--strata 的数量不能为负：{chunk!r}")
        counts[name] = number
    if not counts:
        raise ValueError("--strata 不能为空")
    return counts


def allocate_quotas(n: int, weights: dict[str, float] | None = None,
                    counts: dict[str, int] | None = None) -> dict[str, int]:
    """算每档抽样数：显式 counts 优先，否则按权重最大余数法分配 n。"""
    if counts is not None:
        return {str(key): int(value) for key, value in counts.items()}
    n = int(n)
    if n < 0:
        raise ValueError("n 不能为负")
    weights = {str(key): float(value) for key, value in (weights or DEFAULT_STRATA_WEIGHTS).items()}
    if not weights or any(value < 0 for value in weights.values()):
        raise ValueError("分层权重非法")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("分层权重之和必须为正")
    raw = {key: n * value / total for key, value in weights.items()}
    quota = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = n - sum(quota.values())
    order = list(raw)
    if remainder > 0:
        ranked = sorted(order, key=lambda key: (-(raw[key] - quota[key]), order.index(key)))
        cursor = 0
        while remainder > 0:
            quota[ranked[cursor % len(ranked)]] += 1
            remainder -= 1
            cursor += 1
    return quota


def stratified_sample(pairs: list[dict], quotas: dict[str, int],
                      seed: int) -> tuple[list[dict], dict]:
    """按档位独立抽样；返回 (sampled, shortfalls)。同 seed 结果确定。"""
    grouped: dict[str, list[dict]] = {}
    for pair in pairs:
        maybe_id = pair.get("pair_id") if isinstance(pair, dict) else None
        if maybe_id is None:
            continue
        stratum = str(pair.get("stratum") or "unknown")
        grouped.setdefault(stratum, []).append(pair)
    sampled: list[dict] = []
    shortfalls: dict[str, dict] = {}
    for stratum in quotas:
        rows = sorted(grouped.get(stratum, []), key=lambda item: str(item.get("pair_id")))
        target = int(quotas[stratum])
        take = min(target, len(rows))
        if take < target:
            shortfalls[stratum] = {"requested": target, "available": len(rows)}
        if take <= 0:
            continue
        rng = random.Random(_derive_seed(seed, f"sample::{stratum}"))
        chosen = rng.sample(rows, take)
        sampled.extend(sorted(chosen, key=lambda item: str(item.get("pair_id"))))
    return sampled, shortfalls


def validate_materials(materials) -> list[str]:
    """校验 materials 契约 + 盲材料无泄漏；返回错误列表（空 = 通过）。"""
    if not isinstance(materials, dict):
        return ["materials 必须是 JSON 对象（含 pairs + key）"]
    errors: list[str] = []
    pairs = materials.get("pairs")
    key = materials.get("key")
    if not isinstance(pairs, list) or not pairs:
        errors.append("materials.pairs 必须是非空数组")
    if not isinstance(key, dict) or not key:
        errors.append("materials.key 必须是非空对象（pair_id → 交付侧答案）")
    if errors:
        return errors
    seen: set[str] = set()
    for index, pair in enumerate(pairs):
        where = f"pairs[{index}]"
        if not isinstance(pair, dict):
            errors.append(f"{where} 必须是对象")
            continue
        raw_id = pair.get("pair_id")
        pair_id = str(raw_id).strip() if raw_id is not None else ""
        if not pair_id:
            errors.append(f"{where} 缺少 pair_id")
        elif pair_id in seen:
            errors.append(f"pair_id 重复：{pair_id}")
        else:
            seen.add(pair_id)
        stratum = pair.get("stratum")
        if not isinstance(stratum, str) or not stratum.strip():
            errors.append(f"{where}({pair_id}) 缺少 stratum")
        for field in ("candidate_a", "candidate_b"):
            value = pair.get(field)
            if not isinstance(value, dict) or not value:
                errors.append(f"{where}({pair_id}) 缺少 {field} 材料")
        if not isinstance(pair.get("applicant"), dict):
            errors.append(f"{where}({pair_id}) 缺少 applicant 材料")
        for leak in blind_material_leaks(pair):
            errors.append(f"{where}({pair_id}) 盲材料含系统元数据：{leak}")
        entry = key.get(pair_id) if pair_id else None
        if not isinstance(entry, dict):
            if pair_id:
                errors.append(f"key 缺少 {pair_id} 的答案")
            continue
        side = str(entry.get("delivered_side") or "").strip().upper()
        if side not in ("A", "B"):
            errors.append(f"key[{pair_id}].delivered_side 必须是 A/B")
        if entry.get("delivered_id") is None:
            errors.append(f"key[{pair_id}].delivered_id 缺失")
        if entry.get("control_id") is None:
            errors.append(f"key[{pair_id}].control_id 缺失")
        key_stratum = entry.get("stratum")
        if key_stratum is not None and str(key_stratum) != str(stratum):
            errors.append(f"key[{pair_id}].stratum 与 pairs 不一致：{key_stratum} vs {stratum}")
    for raw_id in key:
        if str(raw_id) not in seen:
            errors.append(f"key 含未出现在 pairs 的 pair_id：{raw_id}")
    return errors


def randomize_pairs(sampled: list[dict], materials: dict, seed: int) -> tuple[list[dict], dict]:
    """按 seed 重新随机化 A/B，返回 (blind_pairs, key)。"""
    answer_key: dict[str, dict] = {}
    blind_pairs: list[dict] = []
    for pair in sampled:
        pair_id = str(pair.get("pair_id"))
        entry = materials["key"][pair_id]
        origin_side = str(entry.get("delivered_side")).strip().upper()
        if origin_side == "A":
            delivered, control = pair["candidate_a"], pair["candidate_b"]
        else:
            delivered, control = pair["candidate_b"], pair["candidate_a"]
        rng = random.Random(_derive_seed(seed, f"ab::{pair_id}"))
        if rng.random() < 0.5:
            new_side, candidate_a, candidate_b = "A", delivered, control
        else:
            new_side, candidate_a, candidate_b = "B", control, delivered
        blind_pairs.append({
            "pair_id": pair_id,
            "stratum": str(pair.get("stratum")),
            "applicant": copy.deepcopy(pair.get("applicant") or {}),
            "candidate_a": copy.deepcopy(candidate_a),
            "candidate_b": copy.deepcopy(candidate_b),
        })
        answer_key[pair_id] = {
            "delivered_side": new_side,
            "delivered_id": entry.get("delivered_id"),
            "control_id": entry.get("control_id"),
            "stratum": str(pair.get("stratum")),
        }
    return blind_pairs, answer_key


def build(materials, n: int = DEFAULT_N, seed: int = DEFAULT_SEED,
          strata_counts: dict[str, int] | None = None) -> dict:
    """校验 → 分层抽样 → 随机化 A/B；返回 artifacts（errors 直接 raise）。"""
    errors = validate_materials(materials)
    if errors:
        raise ValueError("materials 校验失败：\n- " + "\n- ".join(errors))
    quotas = allocate_quotas(n, counts=strata_counts)
    available = Counter(str(pair.get("stratum")) for pair in materials["pairs"])
    unknown = sorted(set(available) - set(quotas))
    sampled, shortfalls = stratified_sample(materials["pairs"], quotas, seed)
    blind_pairs, answer_key = randomize_pairs(sampled, materials, seed)
    leaks = blind_material_leaks(blind_pairs)
    if leaks:  # 理论上已被 validate_materials 拦住；transform 后再兜底一次
        raise ValueError("blind_set 含系统元数据：" + ", ".join(leaks))
    if len({pair["pair_id"] for pair in blind_pairs}) != len(blind_pairs):
        raise ValueError("blind_set 的 pair_id 不唯一")
    actual = Counter(pair["stratum"] for pair in blind_pairs)
    warnings: list[str] = []
    if unknown:
        warnings.append("materials 含未配置档位（未抽样）：" + ", ".join(unknown))
    if not blind_pairs:
        raise ValueError("没有可抽样的 pair（检查 materials.stratum 与 --strata）")
    protocol = materials.get("protocol") if isinstance(materials.get("protocol"), str) else None
    return {
        "protocol": protocol or DEFAULT_PROTOCOL,
        "human_protocol": HUMAN_PROTOCOL,
        "seed": int(seed),
        "requested_n": sum(quotas.values()),
        "quotas": quotas,
        "available": dict(sorted(available.items())),
        "strata": dict(sorted(actual.items())),
        "shortfalls": shortfalls,
        "warnings": warnings,
        "pairs": blind_pairs,
        "key": answer_key,
    }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _has_annotation_data(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if any(str(row.get(field) or "").strip()
                   for field in ("winner", "confidence", "notes")):
                return True
    return False


def write_outputs(artifacts: dict, out_dir: Path, force: bool = False) -> dict[str, Path]:
    """写 5 个产物；默认拒绝覆盖已有标注（--force 才重建）。"""
    out_dir = Path(out_dir)
    paths = {
        "blind_set": out_dir / "blind_set.json",
        "key": out_dir / "key.json",
        "annotations_a": out_dir / "annotations_annotator_a.csv",
        "annotations_b": out_dir / "annotations_annotator_b.csv",
        "adjudication": out_dir / "adjudication.csv",
    }
    if not force:
        protected = [path for path in (paths["annotations_a"], paths["annotations_b"])
                     if _has_annotation_data(path)]
        if protected:
            raise FileExistsError(
                "已有标注数据，拒绝覆盖：" + ", ".join(path.name for path in protected)
                + "（如确认重建校准集，用 --force）")
    blind_set = {
        "protocol": artifacts["protocol"],
        "human_protocol": artifacts["human_protocol"],
        "seed": artifacts["seed"],
        "n": len(artifacts["pairs"]),
        "requested_n": artifacts["requested_n"],
        "quotas": artifacts["quotas"],
        "available": artifacts["available"],
        "strata": artifacts["strata"],
        "shortfalls": artifacts["shortfalls"],
        "warnings": artifacts["warnings"],
        "pairs": artifacts["pairs"],
    }
    _write_json(paths["blind_set"], blind_set)
    _write_json(paths["key"], artifacts["key"])
    template = [{"pair_id": pair["pair_id"]} for pair in artifacts["pairs"]]
    _write_csv(paths["annotations_a"], ANNOTATION_COLUMNS, template)
    _write_csv(paths["annotations_b"], ANNOTATION_COLUMNS, template)
    _write_csv(paths["adjudication"], ADJUDICATION_COLUMNS, [])
    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="从 quality_pairwise --emit-materials 生成人工盲评校准集（双人+裁决）")
    parser.add_argument("--materials", required=True, type=Path,
                        help="quality_pairwise --emit-materials 输出的 JSON")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="输出目录（blind_set/key/标注表/裁决表）")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="分层抽样总数（默认 100）")
    parser.add_argument("--strata", default=None,
                        help="显式每档数量，如 near_miss=60,rejected=20,random=20")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="抽样/A-B 随机化种子")
    parser.add_argument("--allow-shortfall", action="store_true",
                        help="某些档位样本不足时仍返回 0（默认返回 1，fail-closed）")
    parser.add_argument("--force", action="store_true", help="覆盖已有标注数据（危险）")
    args = parser.parse_args(argv)

    try:
        strata_counts = parse_strata(args.strata)
        materials = json.loads(args.materials.read_text(encoding="utf-8"))
        artifacts = build(materials, n=args.n, seed=args.seed, strata_counts=strata_counts)
        paths = write_outputs(artifacts, args.out_dir, force=args.force)
    except FileExistsError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    summary = {
        "out_dir": str(args.out_dir),
        "n": len(artifacts["pairs"]),
        "strata": artifacts["strata"],
        "shortfalls": artifacts["shortfalls"],
        "warnings": artifacts["warnings"],
        "files": {name: str(path) for name, path in paths.items()},
    }
    print(json.dumps(summary, ensure_ascii=False))
    if artifacts["warnings"]:
        print("警告：" + "；".join(artifacts["warnings"]), file=sys.stderr)
    if artifacts["shortfalls"]:
        detail = "；".join(f"{key}: 需要 {value['requested']} 只有 {value['available']}"
                           for key, value in artifacts["shortfalls"].items())
        print(f"警告：样本不足（{detail}）", file=sys.stderr)
        if not args.allow_shortfall:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
