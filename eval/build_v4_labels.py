#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 标签工具：从人工 CSV / judge JSON 生成并校验 labels.json（不调模型 API）。

v4 的标签是“申请方-候选人”对的 0-3 分相关性标注，不是 heuristic gold：
  * 0 = 硬冲突；1 = 勉强；2 = 合适；3 = 非常合适。
标签必须覆盖全部 40 个正向场景；labels.json 与 scenarios.json 分开冻结。

输入格式：
  --from-csv PATH
      必需列：pair_id, applicant_id, candidate_id, score, annotator
      可选列：delivered（true/false，默认 true，表示该对是否是系统实际交付对）
      applicant_id 可写 V4_01 / TEST_SCENARIO_V4_01 / V4-01；
      candidate_id 为候选成员 id（正整数）；score 为 0-3 整数。
  --from-judge PATH
      JSON 数组（或 {"labels": [...]}）：每项含 pair_id/applicant/candidate/score，
      可选 annotator（默认 judge-proxy）、delivered；method 记为 judge-proxy。
      该工具只消费输入文件，不实际调用任何模型 API。

用法：
  python3 eval/build_v4_labels.py --from-csv labels.csv --write   # 生成并更新 MANIFEST
  python3 eval/build_v4_labels.py --from-judge judge.json --write
  python3 eval/build_v4_labels.py --check                          # 只读校验冻结标签
  python3 eval/build_v4_labels.py --from-csv labels.csv            # dry-run（不写文件）

labels.json 结构：
  {version, protocol_version, method(human|judge-proxy), source{kind,file,sha256},
   labels[{pair_id,applicant,candidate,delivered,score,annotator}], coverage{...}}
--write 时把 MANIFEST.labels.status 更新为 ready，并记录 labels 文件 sha256。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
FROZEN_DIR = EVAL_DIR / "frozen" / "v4"
SCENARIOS_FILE = "scenarios.json"
MANIFEST_FILE = "MANIFEST.json"
LABELS_FILE = "labels.json"

METHOD_CSV = "human"
METHOD_JUDGE = "judge-proxy"
REQUIRED_CSV_COLUMNS = ("pair_id", "applicant_id", "candidate_id", "score", "annotator")
SCORE_RANGE = (0, 3)
POSITIVE_COUNT = 40


class LabelInputError(ValueError):
    """输入行不合法（CLI 会打印全部错误并退出 1）。"""


# ------------------------------------------------------------------ 读取输入
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_csv_rows(path: Path | str) -> list[dict]:
    """读取人工标注 CSV，返回规范化后的原始行（字段名保持输入列名）。"""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in REQUIRED_CSV_COLUMNS if name not in columns]
        if missing:
            raise LabelInputError(f"CSV 缺少必需列 {missing}（实际列：{columns}）")
        rows = []
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue  # 跳过空行
            rows.append({str(key).strip(): (value or "").strip()
                         for key, value in row.items() if key is not None})
    return rows


def read_judge_rows(path: Path | str) -> list[dict]:
    """读取 judge 标注 JSON（数组或 {"labels": [...]}）。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("labels")
    if not isinstance(payload, list):
        raise LabelInputError("judge JSON 必须是数组或 {\"labels\": [...]} 且 labels 为数组")
    return [dict(row) for row in payload]


# ------------------------------------------------------------------ 生成标签
def _scenario_index(scenarios_data: dict) -> tuple[list[dict], dict[str, str], dict[str, int]]:
    """返回 (正向前提场景, 别名->key, key->正向顺序)。"""
    positives = [item for item in scenarios_data.get("scenarios", []) if item.get("run")]
    alias: dict[str, str] = {}
    order: dict[str, int] = {}
    for index, item in enumerate(positives):
        key = item["key"]
        order[key] = index
        for name in (key, item.get("account"), key.replace("_", "-")):
            if name:
                alias[str(name)] = key
    return positives, alias, order


def _normalize_applicant(value, alias: dict[str, str]) -> str:
    text = str(value or "").strip()
    if not text:
        raise LabelInputError("applicant 为空")
    key = alias.get(text)
    if key is None:
        raise LabelInputError(f"applicant={text!r} 不是 v4 正向场景（可用 key/account）")
    return key


def _parse_int(value, name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise LabelInputError(f"{name}={value!r} 不是整数") from None


def _parse_score(value) -> int:
    score = _parse_int(value, "score")
    low, high = SCORE_RANGE
    if not low <= score <= high:
        raise LabelInputError(f"score={score} 不在 {low}-{high} 范围内")
    return score


def _parse_delivered(value) -> bool:
    if value is None or str(value).strip() == "":
        return True
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "交付"):
        return True
    if text in ("false", "0", "no", "n", "对照", "control"):
        return False
    raise LabelInputError(f"delivered={value!r} 不是布尔值（true/false）")


def build_labels_document(raw_rows: list[dict], method: str, source: dict,
                          scenarios_data: dict) -> dict:
    """把原始标注行规范化为 labels.json 文档；任何一行不合法都抛 LabelInputError。"""
    positives, alias, order = _scenario_index(scenarios_data)
    if not positives:
        raise LabelInputError("scenarios.json 里没有正向场景")
    labels: list[dict] = []
    errors: list[str] = []
    seen_pair_ids: set[str] = set()
    seen_pairs: set[tuple] = set()
    for position, row in enumerate(raw_rows, 1):
        try:
            pair_id = str(row.get("pair_id") or "").strip()
            if not pair_id:
                raise LabelInputError("pair_id 为空")
            if pair_id in seen_pair_ids:
                raise LabelInputError(f"pair_id={pair_id!r} 重复")
            applicant_value = row.get("applicant_id", row.get("applicant"))
            candidate_value = row.get("candidate_id", row.get("candidate"))
            applicant = _normalize_applicant(applicant_value, alias)
            candidate = _parse_int(candidate_value, "candidate")
            if candidate <= 0:
                raise LabelInputError(f"candidate={candidate} 必须是正整数成员 id")
            score = _parse_score(row.get("score"))
            annotator = str(row.get("annotator") or "").strip()
            if not annotator and method == METHOD_JUDGE:
                annotator = METHOD_JUDGE
            if not annotator:
                raise LabelInputError("annotator 为空")
            delivered = _parse_delivered(row.get("delivered"))
            pair = (applicant, candidate)
            if pair in seen_pairs:
                raise LabelInputError(f"重复标注同一对：{pair}")
            seen_pair_ids.add(pair_id)
            seen_pairs.add(pair)
        except LabelInputError as error:
            errors.append(f"第 {position} 行（pair_id={row.get('pair_id')!r}）：{error}")
            continue
        labels.append({
            "pair_id": pair_id,
            "applicant": applicant,
            "candidate": candidate,
            "delivered": delivered,
            "score": score,
            "annotator": annotator,
        })
    if errors:
        raise LabelInputError("\n".join(errors))
    labels.sort(key=lambda item: (order.get(item["applicant"], 999), item["pair_id"]))
    known_keys = {item["key"] for item in positives}
    covered = {item["applicant"] for item in labels}
    missing = sorted(known_keys - covered, key=lambda key: order.get(key, 999))
    scores = {str(score): 0 for score in range(SCORE_RANGE[0], SCORE_RANGE[1] + 1)}
    for item in labels:
        scores[str(item["score"])] += 1
    delivered = sum(1 for item in labels if item["delivered"])
    return {
        "version": scenarios_data.get("version", "v4"),
        "protocol_version": scenarios_data.get("protocol_version"),
        "method": method,
        "source": source,
        "labels": labels,
        "coverage": {
            "positive_scenarios": len(positives),
            "covered": len(covered),
            "missing": missing,
            "label_count": len(labels),
            "scores": scores,
            "annotators": sorted({item["annotator"] for item in labels}),
            "delivered": {"delivered": delivered, "control": len(labels) - delivered},
        },
    }


def dump_labels(labels: dict) -> str:
    """确定性序列化（labels 已按场景顺序排序；重复生成字节一致）。"""
    return json.dumps(labels, ensure_ascii=False, indent=2) + "\n"


# ------------------------------------------------------------------ 校验标签
def check_labels_document(labels: dict, scenarios_data: dict,
                          manifest: dict | None = None,
                          labels_bytes: bytes | None = None,
                          label_file: Path | str | None = None) -> list[str]:
    """校验 labels.json 内容：schema / 覆盖 40 正向 / 分布 / 与 MANIFEST 对齐。"""
    errors: list[str] = []
    positives, alias, order = _scenario_index(scenarios_data)
    known_keys = {item["key"] for item in positives}
    if not isinstance(labels, dict):
        return ["labels.json 根节点必须是对象"]
    if labels.get("version") != scenarios_data.get("version"):
        errors.append(f"labels.version={labels.get('version')!r} 与 scenarios 不一致")
    if labels.get("protocol_version") != scenarios_data.get("protocol_version"):
        errors.append("labels.protocol_version 与 scenarios 不一致")
    method = labels.get("method")
    if method not in (METHOD_CSV, METHOD_JUDGE):
        errors.append(f"labels.method={method!r} 非法（应为 {METHOD_CSV}/{METHOD_JUDGE}）")
    source = labels.get("source")
    if not isinstance(source, dict) or not source.get("kind") or not source.get("sha256"):
        errors.append("labels.source 必须包含 kind 与 sha256")
    entries = labels.get("labels")
    if not isinstance(entries, list) or not entries:
        return errors + ["labels.labels 必须是非空数组"]
    required = ("pair_id", "applicant", "candidate", "delivered", "score", "annotator")
    seen_pair_ids: set[str] = set()
    seen_pairs: set[tuple] = set()
    covered: set[str] = set()
    scores = {str(score): 0 for score in range(SCORE_RANGE[0], SCORE_RANGE[1] + 1)}
    bad_rows = 0
    for index, item in enumerate(entries):
        prefix = f"labels[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 不是对象")
            bad_rows += 1
            continue
        missing = [name for name in required if name not in item]
        if missing:
            errors.append(f"{prefix} 缺字段 {missing}")
            bad_rows += 1
            continue
        pair_id = item["pair_id"]
        if not isinstance(pair_id, str) or not pair_id.strip():
            errors.append(f"{prefix} pair_id 非法：{pair_id!r}")
            bad_rows += 1
            continue
        if pair_id in seen_pair_ids:
            errors.append(f"{prefix} pair_id={pair_id!r} 重复")
        seen_pair_ids.add(pair_id)
        applicant = item["applicant"]
        if applicant not in known_keys:
            errors.append(f"{prefix} applicant={applicant!r} 不是 v4 正向场景 key")
        else:
            covered.add(applicant)
        candidate = item["candidate"]
        if not isinstance(candidate, int) or candidate <= 0:
            errors.append(f"{prefix} candidate={candidate!r} 必须是正整数成员 id")
        pair = (applicant, candidate)
        if pair in seen_pairs:
            errors.append(f"{prefix} 重复标注同一对 {pair}")
        seen_pairs.add(pair)
        score = item["score"]
        if not isinstance(score, int) or not SCORE_RANGE[0] <= score <= SCORE_RANGE[1]:
            errors.append(f"{prefix} score={score!r} 必须是 0-3 整数")
        else:
            scores[str(score)] += 1
        if not isinstance(item["delivered"], bool):
            errors.append(f"{prefix} delivered 必须是布尔值")
        annotator = item["annotator"]
        if not isinstance(annotator, str) or not annotator.strip():
            errors.append(f"{prefix} annotator 必须是非空字符串")

    coverage = labels.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("labels.coverage 缺失")
        coverage = {}
    missing_keys = sorted(known_keys - covered, key=lambda key: order.get(key, 999))
    if coverage.get("positive_scenarios") != len(positives):
        errors.append(f"coverage.positive_scenarios={coverage.get('positive_scenarios')!r} "
                      f"!= {len(positives)}")
    if coverage.get("covered") != len(covered):
        errors.append(f"coverage.covered={coverage.get('covered')!r} != {len(covered)}")
    if coverage.get("missing") != missing_keys:
        errors.append(f"coverage.missing 与逐条复核不一致：{coverage.get('missing')!r} "
                      f"!= {missing_keys!r}")
    if coverage.get("label_count") != len(entries):
        errors.append(f"coverage.label_count={coverage.get('label_count')!r} != {len(entries)}")
    if coverage.get("scores") != scores:
        errors.append(f"coverage.scores 与逐条统计不一致：{coverage.get('scores')!r} != {scores!r}")
    delivered = sum(1 for item in entries if item.get("delivered") is True)
    if (coverage.get("delivered") or {}) != {"delivered": delivered,
                                             "control": len(entries) - delivered}:
        errors.append("coverage.delivered 与逐条统计不一致")
    if missing_keys:
        errors.append(f"标签未覆盖全部 40 个正向场景，缺 {len(missing_keys)} 个：{missing_keys}")

    if manifest is not None:
        labels_block = manifest.get("labels") or {}
        if labels_block.get("status") != "ready":
            errors.append(f"MANIFEST.labels.status={labels_block.get('status')!r}，应为 ready")
        if labels_bytes is not None:
            declared = labels_block.get("sha256")
            if not declared:
                errors.append("MANIFEST.labels 缺少 sha256（labels 已生成时必须记录指纹）")
            elif declared != _sha256_bytes(labels_bytes):
                errors.append("MANIFEST.labels.sha256 与 labels.json 实际字节不一致")
    return errors


def check_labels_file(labels_path: Path | str, scenarios_data: dict,
                      manifest: dict | None = None,
                      repo_root: Path | str = REPO) -> list[str]:
    """校验磁盘上的 labels.json（供 check_v4_freeze / --check 复用）。"""
    labels_path = Path(labels_path)
    if not labels_path.is_file():
        return [f"labels.json 不存在：{labels_path}"]
    labels_bytes = labels_path.read_bytes()
    try:
        labels = json.loads(labels_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"labels.json 不是合法 UTF-8 JSON：{error}"]
    _ = repo_root  # 预留：未来的候选池归属校验
    return check_labels_document(labels, scenarios_data, manifest, labels_bytes)


# ------------------------------------------------------------------ 写盘更新
def _manifest_file(base: Path, name: str, repo_root: Path) -> str:
    try:
        return (Path(base) / name).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return name


def write_labels(labels: dict, base: Path | str | None = None,
                 repo_root: Path | str = REPO) -> dict:
    """写 labels.json 并更新 MANIFEST.labels（status=ready + sha256/count）。"""
    base_dir = Path(base) if base else FROZEN_DIR
    root = Path(repo_root)
    manifest_path = base_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"缺少 {manifest_path}，请先运行 build_v4_scenarios.py --write")
    scenarios_path = base_dir / SCENARIOS_FILE
    if not scenarios_path.is_file():
        raise FileNotFoundError(f"缺少 {scenarios_path}，请先运行 build_v4_scenarios.py --write")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared_scenarios = (manifest.get("scenarios") or {}).get("sha256")
    actual_scenarios = _sha256_file(scenarios_path)
    if declared_scenarios != actual_scenarios:
        raise ValueError("scenarios.json 与 MANIFEST.scenarios.sha256 不一致："
                         "场景已漂移，拒绝为旧场景写标签，请先重冻场景")
    if labels.get("protocol_version") != manifest.get("protocol_version"):
        raise ValueError("labels.protocol_version 与 MANIFEST.protocol_version 不一致")
    labels_text = dump_labels(labels)
    labels_bytes = labels_text.encode("utf-8")
    labels_path = base_dir / LABELS_FILE
    labels_path.write_text(labels_text, encoding="utf-8")
    block = dict(manifest.get("labels") or {})
    block.update({
        "status": "ready",
        "method": labels["method"],
        "file": _manifest_file(base_dir, LABELS_FILE, root),
        "sha256": _sha256_bytes(labels_bytes),
        "count": len(labels["labels"]),
        "source": (labels.get("source") or {}).get("kind"),
    })
    manifest["labels"] = block
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return {"labels_path": labels_path, "manifest_path": manifest_path,
            "labels_bytes": labels_bytes, "manifest": manifest}


def load_scenarios(base: Path | str | None = None) -> dict:
    base_dir = Path(base) if base else FROZEN_DIR
    path = base_dir / SCENARIOS_FILE
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {path}，请先运行 build_v4_scenarios.py --write")
    return json.loads(path.read_text(encoding="utf-8"))


def check(base: Path | str | None = None, repo_root: Path | str = REPO) -> list[str]:
    """--check：只读校验冻结的 labels.json（含 MANIFEST 指纹）。"""
    base_dir = Path(base) if base else FROZEN_DIR
    scenarios = load_scenarios(base_dir)
    labels_path = base_dir / LABELS_FILE
    manifest_path = base_dir / MANIFEST_FILE
    manifest = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return check_labels_file(labels_path, scenarios, manifest, repo_root)


# ---------------------------------------------------------------------- CLI
def _sources_from_args(args) -> tuple[list[dict], str, dict]:
    """按参数读取输入文件，返回 (原始行, method, source)。"""
    if args.from_csv:
        path = Path(args.from_csv)
        rows = read_csv_rows(path)
        source = {"kind": "csv", "file": _display_path(path),
                  "sha256": _sha256_file(path)}
        return rows, METHOD_CSV, source
    path = Path(args.from_judge)
    rows = read_judge_rows(path)
    source = {"kind": "json-judge", "file": _display_path(path),
              "sha256": _sha256_file(path)}
    return rows, METHOD_JUDGE, source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v4 标签生成/校验（不调模型 API）")
    parser.add_argument("--from-csv", type=Path, default=None,
                        help="人工标注 CSV（pair_id,applicant_id,candidate_id,score,annotator）")
    parser.add_argument("--from-judge", type=Path, default=None,
                        help="judge 标注 JSON（数组，score 0-3，method 记为 judge-proxy）")
    parser.add_argument("--check", action="store_true", help="只读校验冻结的 labels.json")
    parser.add_argument("--write", action="store_true",
                        help="写 labels.json 并把 MANIFEST.labels.status 更新为 ready")
    parser.add_argument("--frozen-dir", type=Path, default=None,
                        help="冻结目录（默认 eval/frozen/v4）")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    base = args.frozen_dir or FROZEN_DIR
    if args.check:
        if args.from_csv or args.from_judge:
            parser.error("--check 不能与 --from-csv/--from-judge 同时使用")
        errors = check(base)
        if errors:
            for error in errors:
                print(f"[FAIL] {error}")
            return 1
        labels = json.loads((base / LABELS_FILE).read_text(encoding="utf-8"))
        coverage = labels.get("coverage") or {}
        print(f"[OK] labels.json 校验通过：{coverage.get('label_count')} 条，"
              f"覆盖 {coverage.get('covered')}/{coverage.get('positive_scenarios')} 个正向场景，"
              f"method={labels.get('method')}，scores={coverage.get('scores')}，"
              f"annotators={coverage.get('annotators')}")
        return 0
    if args.from_csv and args.from_judge:
        parser.error("--from-csv 与 --from-judge 只能选一个")
    if not args.from_csv and not args.from_judge:
        parser.error("需要 --from-csv/--from-judge 生成，或 --check 校验")
    try:
        raw_rows, method, source = _sources_from_args(args)
        scenarios = load_scenarios(base)
        document = build_labels_document(raw_rows, method, source, scenarios)
    except (LabelInputError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1
    errors = check_labels_document(document, scenarios)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    coverage = document["coverage"]
    if not args.write:
        if not args.quiet:
            print(f"[OK] 输入校验通过（dry-run，未写文件）：{coverage['label_count']} 条，"
                  f"覆盖 {coverage['covered']}/{coverage['positive_scenarios']} 个正向场景，"
                  f"method={method}，scores={coverage['scores']}")
            print("     加 --write 才会写 labels.json 并更新 MANIFEST.labels.status=ready")
        return 0
    try:
        result = write_labels(document, base)
    except (FileNotFoundError, ValueError) as error:
        print(f"[FAIL] {error}")
        return 1
    errors = check_labels_file(result["labels_path"], load_scenarios(base),
                               result["manifest"], REPO)
    if errors:
        for error in errors:
            print(f"[FAIL] 写入后自检失败：{error}")
        return 1
    if not args.quiet:
        block = result["manifest"]["labels"]
        print(f"写入 {result['labels_path']}")
        print(f"更新 {result['manifest_path']}：labels.status=ready，"
              f"sha256={block['sha256']}，count={block['count']}")
        print(f"标签 {coverage['label_count']} 条，覆盖 {coverage['covered']}/"
              f"{coverage['positive_scenarios']} 个正向场景，method={method}，"
              f"scores={coverage['scores']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
