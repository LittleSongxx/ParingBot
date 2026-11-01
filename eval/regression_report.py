#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键质量回归报告：quality checks + heuristic golden + consensus golden。

用法：
  python eval/regression_report.py --bundle analysis/quality-bundles/expanded-latest.json \
      --out analysis/regression-report.md --json analysis/regression-report.json

CI 用固定 fixture 跑，带最低指标门禁；真实 bundle 在本地/评测机跑。
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import golden_matching  # noqa: E402
import quality_checks  # noqa: E402
import safety_checks  # noqa: E402


def load_labels(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def agreement_rows(bundle: dict, labels: dict, consensus: dict) -> list[dict]:
    by_a = {item["member_id"]: set(item.get("gold_ids") or []) for item in labels.get("labels", [])}
    by_a_name = {item.get("username"): set(item.get("gold_ids") or [])
                 for item in labels.get("labels", []) if item.get("username")}
    by_c = {item["member_id"]: set(item.get("gold_ids") or []) for item in consensus.get("labels", [])}
    by_c_name = {item.get("username"): set(item.get("gold_ids") or [])
                 for item in consensus.get("labels", []) if item.get("username")}
    rows = []
    for run in bundle.get("runs", []):
        app = run.get("applicant") or {}
        member_id = app.get("id")
        username = app.get("username")
        left = by_a.get(member_id) or by_a_name.get(username)
        right = by_c.get(member_id) or by_c_name.get(username)
        if left is None or right is None:
            continue
        rows.append({"run_id": run.get("run", {}).get("id"), "applicant": app.get("nickname"),
                     "overlap": len(left & right),
                     "jaccard": round(len(left & right) / len(left | right), 4) if left | right else 0.0})
    return rows


def load_scenario_summary(directory: Path) -> list[dict]:
    """扫描 scenario-matrix-*/matrix.json，每个场景保留最新一次真实运行/阻断。"""
    if not directory.exists():
        return []
    best: dict[str, dict] = {}
    for path in sorted(directory.glob("scenario-matrix-*/matrix.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for scenario in data.get("scenarios", []):
            key = scenario.get("key")
            if not key:
                continue
            runs = scenario.get("runs") or []
            latest = max(runs, key=lambda row: row.get("run_id") or 0) if runs else None
            candidate = {
                "key": key, "title": scenario.get("title"), "account": scenario.get("account"),
                "readiness": scenario.get("status") or ("有运行" if runs else "未运行"),
                "run_status": latest.get("run_status") if latest else None,
                "total_round": latest.get("total_round") if latest else None,
                "delivered": latest.get("delivered") if latest else None,
                "requested": (latest.get("funnel") or {}).get("deliver_count") if latest else None,
                "wall_seconds": latest.get("wall_seconds") if latest else None,
                "run_id": latest.get("run_id") if latest else None,
                # 有 run 的场景按 run_id 选最新；纯阻断场景按文件修改时间选最新
                "_rank": latest.get("run_id") if latest else -int(path.stat().st_mtime),
            }
            previous = best.get(key)
            if previous is None or candidate["_rank"] > previous["_rank"]:
                best[key] = candidate
    return [best[key] for key in sorted(best, key=lambda item: int(item[1:]))]


def build_report(bundle_path: Path, labels_path: Path, consensus_path: Path,
                 scenario_dir: Path | None = None) -> tuple[dict, str]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    labels = load_labels(labels_path)
    consensus = load_labels(consensus_path)
    checks = [quality_checks.check_run(item) for item in bundle.get("runs", [])]
    quality_errors = [error for check in checks for error in check["errors"]]
    safety_findings = safety_checks.scan_bundle(bundle)
    safety_errors = [item for item in safety_findings if item["severity"] == "error"]
    safety_warnings = [item for item in safety_findings if item["severity"] == "warning"]
    heuristic = golden_matching.evaluate(bundle_path, labels_path)
    consensus_metrics = golden_matching.evaluate(bundle_path, consensus_path)
    agreement = agreement_rows(bundle, labels, consensus)
    scenarios = load_scenario_summary(scenario_dir) if scenario_dir else []
    pressure_keys = [item.strip() for item in getattr(build_report, "_pressure", "") .split(",") if item.strip()]
    pressure_min = getattr(build_report, "_pressure_min", 7)
    pressure_rows = [item for item in scenarios if item["key"] in pressure_keys]
    pressure_failures = [item for item in pressure_rows
                         if item.get("run_status") != "已完成"
                         or (item.get("delivered") or 0) < pressure_min]
    result = {
        "bundle": str(bundle_path),
        "runs": len(bundle.get("runs", [])),
        "quality": {
            "runs": len(checks),
            "hard_rule_violations": sum(len(item["hard_rule_violations"]) for item in checks),
            "summary_errors": sum(len(item["summary_errors"]) for item in checks),
            "evidence_missing": sum(item["evidence"]["delivered"] - item["evidence"]["with_evidence"] for item in checks),
            "errors": quality_errors,
        },
        "safety": {"errors": len(safety_errors), "warnings": len(safety_warnings),
                   "findings": safety_findings},
        "heuristic": heuristic["aggregate"],
        "consensus": consensus_metrics["aggregate"],
        "agreement": {
            "runs": len(agreement),
            "avg_overlap": round(sum(item["overlap"] for item in agreement) / len(agreement), 2) if agreement else 0.0,
            "avg_jaccard": round(sum(item["jaccard"] for item in agreement) / len(agreement), 4) if agreement else 0.0,
        },
        "rows": agreement,
        "scenarios": scenarios,
        "pressure": {"keys": pressure_keys, "min_delivery": pressure_min,
                     "rows": pressure_rows,
                     "failures": [item["key"] for item in pressure_failures]},
    }
    lines = ["# ParingBot 质量回归报告", "", f"- 数据包：`{bundle_path}`", f"- runs：{result['runs']}", "",
             "## 安全 / 隐私", "",
             f"- PII/secret 错误：**{len(safety_errors)}**；warning：{len(safety_warnings)}", "",
             "## 质量检查", "",
             "| 指标 | 值 |", "|---|---|",
             f"| 硬规则违规 | {result['quality']['hard_rule_violations']} |",
             f"| summary 不一致 | {result['quality']['summary_errors']} |",
             f"| 交付缺证据 | {result['quality']['evidence_missing']} |", "",
             "## Golden 指标", "",
             "| 评分器 | Precision@K | Recall@K | |", "|---|---|---|---|",
             f"| heuristic | {heuristic['aggregate']['avg_precision_at_k']:.2%} | {heuristic['aggregate']['avg_recall_at_k']:.2%} | |",
             f"| consensus | {consensus_metrics['aggregate']['avg_precision_at_k']:.2%} | {consensus_metrics['aggregate']['avg_recall_at_k']:.2%} | |", "",
             "## heuristic vs consensus 一致度", "",
             f"- 覆盖 runs：{result['agreement']['runs']}",
             f"- top8 平均重合：**{result['agreement']['avg_overlap']}/8**",
             f"- 平均 Jaccard：**{result['agreement']['avg_jaccard']:.2%}**", ""]
    if pressure_keys:
        lines += ["## 压力场景门禁", "", f"阈值：已完成且交付 ≥ {pressure_min} 人", "",
                  "| 场景 | 运行 | 交付 | 结果 |", "|---|---|---|---|"]
        for item in pressure_rows:
            prefix = "通过" if item not in pressure_failures else "**失败**"
            delivered = item.get("delivered")
            requested = item.get("requested")
            lines.append(f"| {item['key']} | {item.get('run_status') or '—'} | "
                         f"{(str(delivered) + '/' + str(requested)) if delivered is not None and requested else '—'} | {prefix} |")
        if not pressure_rows:
            lines.append("| — | 无场景报告 | — | 跳过 |")
        lines.append("")
    if scenarios:
        lines += ["## 场景矩阵摘要", "", "| 场景 | 标题 | readiness | 运行 | 轮次 | 交付 | 耗时 |",
                  "|---|---|---|---|---|---|---|"]
        for item in scenarios:
            delivered = item.get("delivered")
            requested = item.get("requested")
            delivery = (f"{delivered}/{requested}" if delivered is not None else "—")
            lines.append(f"| {item['key']} | {item.get('title') or ''} | {item.get('readiness') or ''} | "
                         f"{item.get('run_status') or '—'} | {item.get('total_round') or '—'} | {delivery} | "
                         f"{item.get('wall_seconds') or '—'} |")
        lines.append("")
    if quality_errors:
        lines += ["## 失败项", ""] + [f"- {error}" for error in quality_errors] + [""]
    return result, "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=Path("eval/golden/matching_labels.json"))
    parser.add_argument("--consensus", type=Path, default=Path("eval/golden/consensus_labels.json"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--min-precision", type=float, default=0.0)
    parser.add_argument("--min-consensus", type=float, default=0.0)
    parser.add_argument("--scenario-dir", type=Path, default=Path("eval/reports"))
    parser.add_argument("--pressure-scenarios", default="S6,S12,S14,S16,S17,S20")
    parser.add_argument("--pressure-min-delivery", type=int, default=7)
    args = parser.parse_args(argv)
    build_report._pressure = args.pressure_scenarios
    build_report._pressure_min = args.pressure_min_delivery
    result, markdown = build_report(args.bundle, args.labels, args.consensus, args.scenario_dir)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON 报告：{args.json}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"Markdown 报告：{args.out}")
    failed = bool(result["quality"]["errors"]) or bool(result["safety"]["errors"])
    if result["pressure"]["failures"]:
        failed = True
        print("压力场景门禁失败：" + "、".join(result["pressure"]["failures"]))
    if result["heuristic"]["avg_precision_at_k"] < args.min_precision:
        failed = True
        print(f"heuristic Precision {result['heuristic']['avg_precision_at_k']:.2%} < {args.min_precision:.2%}")
    if result["consensus"]["avg_precision_at_k"] < args.min_consensus:
        failed = True
        print(f"consensus Precision {result['consensus']['avg_precision_at_k']:.2%} < {args.min_consensus:.2%}")
    print(json.dumps({"quality": result["quality"], "heuristic": result["heuristic"],
                      "consensus": result["consensus"], "agreement": result["agreement"]}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
