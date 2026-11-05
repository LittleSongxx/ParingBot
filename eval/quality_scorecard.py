#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""质量评分卡：把多次评测 artifact 汇总成“能/不能声称什么”的一页结论。

输入（任选、可重复）：
  --run DIR       一次 live-eval/v4-pilot artifact 目录（自动找 matrix + report + content/judge）
  --matrix FILE   scenario-matrix-*/matrix.json 或 artifact 目录
  --content FILE  content_quality.py --json 产物
  --judge FILE    judge.py --json 产物
  --out FILE      输出 markdown（可选）
  --json FILE     输出机器可读 JSON（可选）

关键口径：
* 按“场景-run”聚合，交付均值/失败率都带 Wilson 或 bootstrap CI；
* 同一场景跨 run 的交付差异 >= 2 标 unstable；有失败单独标；
* target 达成率接近 100% 时标 delivery_headroom=false（v3 已饱和，不能拿来证明提升）；
* 没有 E3 人工盲评时 quality_claim_allowed 永远为 false；内容/judge 只作为探索性代理信号。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lib import metrics  # noqa: E402

COMPLETED = {"已完成", "完成", "completed", "Completed", "done", "DONE"}


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _discover(artifact: Path) -> dict:
    artifact = Path(artifact)
    report = None
    for name in ("regression-report.json", "v4-pilot-report.json"):
        if (artifact / name).is_file():
            report = artifact / name
            break
    matrices = sorted(artifact.glob("eval/reports/scenario-matrix-*/matrix.json"))
    content = artifact / "content-report.json"
    judge = artifact / "judge-report.json"
    return {
        "matrix": matrices[-1] if matrices else None,
        "report": report,
        "content": content if content.is_file() else None,
        "judge": judge if judge.is_file() else None,
    }


def _scenario_target(scenario: dict, requested: int) -> int:
    expect = scenario.get("expect") or {}
    target = expect.get("target")
    if target is None:
        capacity = scenario.get("ex_ante_capacity") or {}
        eligible = (capacity.get("eligible_unbounded")
                    or expect.get("ex_ante_unbounded")
                    or capacity.get("eligible")
                    or expect.get("ex_ante_eligible"))
        target = min(requested, int(eligible)) if eligible else requested
    return max(0, int(target))


def collect_runs(matrix_paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for matrix_path in matrix_paths:
        payload = _read(matrix_path)
        for scenario in payload.get("scenarios", []) or []:
            runs = scenario.get("runs") or []
            if not runs:
                continue  # 负向/被阻断场景没有 trial，不进入交付统计
            requested = int((scenario.get("expect") or {}).get("requested") or 8)
            target = _scenario_target(scenario, requested)
            expect = scenario.get("expect") or {}
            eligible_unbounded = int(expect.get("ex_ante_unbounded") or 0)
            for run in scenario.get("runs") or []:
                delivered = int(run.get("delivered") or 0)
                counts = run.get("counts") or {}
                discovered = int(counts.get("total") or 0)
                passed = int(counts.get("passed") or 0)
                rejected = int(counts.get("rejected") or 0)
                rows.append({
                    "scenario": scenario.get("key"),
                    "requested": requested,
                    "target": target,
                    "delivered": delivered,
                    "discovered": discovered,
                    "passed": passed,
                    "rejected": rejected,
                    "rounds": int(run.get("total_round") or 0),
                    "eligible_unbounded": eligible_unbounded,
                    "coverage": round(min(discovered / target, 1.0), 4) if target else 0.0,
                    "target_attainment": round(min(delivered / target, 1.0), 4) if target else 0.0,
                    "status": run.get("run_status"),
                    "error_message": run.get("error_message"),
                    "wall_seconds": run.get("wall_seconds"),
                    "source": str(matrix_path),
                })
    return rows


def summarize_runs(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["scenario"], []).append(row)
    per_scenario = {}
    for key, values in sorted(grouped.items()):
        delivered = [int(item.get("delivered", 0)) for item in values]
        attainment = [float(item.get("target_attainment", 0.0)) for item in values]
        coverage = [float(item.get("coverage", 0.0)) for item in values]
        discovered = [int(item.get("discovered", 0)) for item in values]
        passed = [int(item.get("passed", 0)) for item in values]
        rejected = [int(item.get("rejected", 0)) for item in values]
        rounds = [int(item.get("rounds", 0)) for item in values]
        walls = [float(item.get("wall_seconds") or 0) for item in values]
        statuses = [item.get("status") for item in values]
        failures = sum(1 for item in values if item["status"] not in COMPLETED)
        per_scenario[key] = {
            "runs": len(values),
            "delivered": delivered,
            "delivered_mean": round(statistics.mean(delivered), 4),
            "delivered_min": min(delivered),
            "delivered_max": max(delivered),
            "delivered_range": max(delivered) - min(delivered),
            "target": values[0]["target"],
            "target_attainment_mean": round(statistics.mean(attainment), 4),
            "coverage_mean": round(statistics.mean(coverage), 4),
            "coverage_min": min(coverage),
            "coverage_max": max(coverage),
            "coverage_range": round(max(coverage) - min(coverage), 4),
            "discovered": discovered,
            "passed": passed,
            "rejected": rejected,
            "rounds": rounds,
            "wall_seconds": walls,
            "statuses": statuses,
            "audit_rejection_rate": round(sum(rejected) / max(1, sum(discovered)), 4),
            "failures": failures,
            "unstable": (max(delivered) - min(delivered) >= 2
                         or (max(coverage) - min(coverage) >= 0.5)),
            "has_failure": failures > 0,
        }
    failures = sum(1 for row in rows if row["status"] not in COMPLETED)
    failure_details = [
        {"scenario": row["scenario"], "status": row.get("status"),
         "error_message": (row.get("error_message") or "")[:300]}
        for row in rows if row["status"] not in COMPLETED
    ]
    target_means = [item["target_attainment_mean"] for item in per_scenario.values()]
    delivery_means = [statistics.mean(item["delivered"]) for item in per_scenario.values()]
    coverage_means = [item["coverage_mean"] for item in per_scenario.values()]
    target_ci = metrics.bootstrap_ci(target_means) if target_means else None
    failure_ci = metrics.wilson_ci(failures, len(rows)) if rows else None
    expected_consistency = sum(
        1 for item in per_scenario.values() if len(set(item["delivered"])) == 1)
    return {
        "scenario_runs": len(rows),
        "scenarios": len(per_scenario),
        "failures": failures,
        "failure_rate": round(failures / len(rows), 4) if rows else 0.0,
        "failure_ci95": failure_ci,
        "delivery_mean": round(statistics.mean(delivery_means), 4) if delivery_means else 0.0,
        "target_attainment": round(statistics.mean(target_means), 4) if target_means else 0.0,
        "target_ci95": target_ci,
        "same_scenario_consistency": round(expected_consistency / len(per_scenario), 4) if per_scenario else 0.0,
        "discovery_coverage": round(statistics.mean(coverage_means), 4) if coverage_means else 0.0,
        "audit_rejection_rate": round(
            sum(sum(item["rejected"]) for item in per_scenario.values())
            / max(1, sum(sum(item["discovered"]) for item in per_scenario.values())), 4),
        "low_coverage_scenarios": sorted(key for key, item in per_scenario.items()
                                         if item["coverage_mean"] < 0.99),
        "unstable_scenarios": sorted(key for key, item in per_scenario.items() if item["unstable"]),
        "failed_scenarios": sorted(key for key, item in per_scenario.items() if item["has_failure"]),
        "failure_details": failure_details,
        "per_scenario": per_scenario,
        "delivery_headroom": not (target_means and statistics.mean(target_means) >= 0.99),
    }


def load_content(path: Path | None) -> dict | None:
    if not path:
        return None
    data = _read(path)
    return {"n": data.get("n"), "means": data.get("means"), "ci95": data.get("ci95"),
            "rule_warnings": len(data.get("rule_warnings") or []),
            "ceiling_effect": data.get("ceiling_effect"), "credible": data.get("credible"),
            "judge_model": data.get("judge_model"), "source": str(path)}


def load_judge(path: Path | None) -> dict | None:
    if not path:
        return None
    data = _read(path)
    aggregate = data.get("aggregate") or data.get("summary") or {}
    return {
        "mode": data.get("mode"),
        "model": data.get("model") or data.get("judge_model"),
        "pairs": aggregate.get("pairs") or aggregate.get("n"),
        "valid": aggregate.get("valid"),
        "delivered_win_rate": aggregate.get("delivered_win_rate",
                                             aggregate.get("top_win_rate")),
        "position_consistency": aggregate.get("position_consistency"),
        "ci95": aggregate.get("ci95") or data.get("ci95"),
        "source": str(path),
    }


def build(markdown_paths: list[Path], report_paths: list[Path],
          content_paths: list[Path], judge_paths: list[Path]) -> dict:
    rows = collect_runs(markdown_paths)
    summary = summarize_runs(rows)
    reports = []
    for path in report_paths:
        data = _read(path)
        cost = data.get("cost") or {}
        latency = data.get("latency") or {}
        if "delivery" in data:
            reports.append({"source": str(path), "token": cost.get("total_tokens"),
                            "p50": latency.get("p50_seconds"), "p95": latency.get("p95_seconds"),
                            "gates_failed": (data.get("gates") or {}).get("failed")})
        else:
            reports.append({"source": str(path),
                            "delivery_rate": data.get("delivery_rate"),
                            "target_attainment": data.get("target_attainment"),
                            "failures": data.get("failures")})
    contents = [load_content(path) for path in content_paths]
    judges = [load_judge(path) for path in judge_paths]
    claims = {
        "quality_claim_allowed": False,
        "reason": "没有 E3 人工盲评（双人 rubric + kappa>=0.6）；代理结果只能作探索性信号",
        "delivery_headroom": summary["delivery_headroom"],
        "pass_k_stable": not summary["unstable_scenarios"] and not summary["failed_scenarios"],
    }
    return {
        "summary": summary,
        "reports": reports,
        "content": contents[0] if contents else None,
        "judge": judges[0] if judges else None,
        "claims": claims,
    }


def render(result: dict) -> str:
    summary = result["summary"]
    failure_ci = summary.get("failure_ci95") or {"lo": 0.0, "hi": 0.0}
    target_ci = summary.get("target_ci95") or {"lo": 0.0, "hi": 0.0}
    lines = [
        "# ParingBot 质量评分卡（自动汇总）",
        "",
        "> 本卡只汇总已归档 artifact；没有 E3 人工盲评时，任何“匹配质量”结论仍不可对外。",
        "",
        "## 1. 交付/稳定性",
        "",
        f"- 场景-run：**{summary['scenario_runs']}**；场景：**{summary['scenarios']}**；失败：**{summary['failures']}**"
        f"（失败率 {summary['failure_rate']:.2%}，Wilson 95% CI "
        f"[{failure_ci['lo']:.1%}, {failure_ci['hi']:.1%}]）",
        f"- target 达成率：**{summary['target_attainment']:.2%}**"
        f"（95% CI [{target_ci['lo']:.1%}, {target_ci['hi']:.1%}]）",
        f"- 同场景跨 run 完全一致率：**{summary['same_scenario_consistency']:.1%}**；"
        f"候选发现覆盖率（discovered/target）：**{summary['discovery_coverage']:.1%}**；"
        f"审核否决率（rejected/discovered）：**{summary['audit_rejection_rate']:.1%}**",
        f"- 覆盖率不足场景：{summary['low_coverage_scenarios'] or '无'}；"
        f"不稳定场景：{summary['unstable_scenarios'] or '无'}；有失败场景：{summary['failed_scenarios'] or '无'}",
        f"- 不稳定判定：同一场景跨 run 交付极差≥2 **或** 候选发现覆盖率极差≥0.5",
        f"- delivery_headroom：**{summary['delivery_headroom']}**"
        + ("（target 已接近 100%，交付指标无提升空间）" if not summary["delivery_headroom"] else ""),
        "",
        "| 场景 | runs | 交付序列 | 均值 | target | 发现覆盖 | 失败 | unstable |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, item in summary["per_scenario"].items():
        lines.append(f"| {key} | {item['runs']} | {item['delivered']} | {item['delivered_mean']} | "
                     f"{item['target']} | {item['coverage_mean']:.0%} | {item['failures']} | {item['unstable']} |")
    unstable = summary.get("unstable_scenarios") or []
    if unstable:
        lines += ["", "### 不稳定场景 trial 明细（发现不足 vs 审核否决）", "",
                  "| 场景 | trial | discovered | passed | rejected | delivered | coverage | rounds | wall(s) | status |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for key in unstable:
            item = summary["per_scenario"][key]
            for index, value in enumerate(item["delivered"]):
                status = (item.get("statuses") or [])[index] if index < len(item.get("statuses") or []) else ""
                lines.append(
                    f"| {key} | {index + 1} | {item['discovered'][index]} | {item['passed'][index]} | "
                    f"{item['rejected'][index]} | {value} | {item['delivered'][index] / item['target']:.0%} | "
                    f"{item['rounds'][index]} | {item['wall_seconds'][index]:.1f} | {status} |")
    if summary.get("failure_details"):
        lines.append("")
        lines.append("失败明细：")
        for item in summary["failure_details"]:
            lines.append(f"- {item['scenario']}: {item['status']}；{item['error_message'] or '（无 error_message）'}")
    lines += ["", "## 2. 质量代理信号（E2.5/E2，探索）"]
    content = result.get("content")
    if content:
        means = content.get("means") or {}
        lines.append(
            f"- 内容质量：n={content.get('n')}，overall **{means.get('overall')}**，faithful **{means.get('faithful')}**，"
            f"规则 warning {content.get('rule_warnings')} 条；天花板={content.get('ceiling_effect')}；"
            f"credible={content.get('credible')}；judge={content.get('judge_model')}（n=20 不代表质量达标）")
    judge = result.get("judge")
    if judge:
        ci = judge.get("ci95") or {}
        win = judge.get("delivered_win_rate")
        win_ci = ci.get("delivered_win_rate") if isinstance(ci, dict) else None
        cons = judge.get("position_consistency")
        lines.append(
            f"- 成对 judge：pairs={judge.get('pairs')}（valid={judge.get('valid')}），delivered 胜率 "
            f"**{win:.1%}**" if isinstance(win, (int, float)) else "- 成对 judge：无有效数据")
        if isinstance(win, (int, float)) and win_ci:
            lines.append(f"  （Wilson 95% CI {win_ci.get('lo'):.1%}–{win_ci.get('hi'):.1%}）；"
                         f"位置一致性 {cons:.2f}；模型={judge.get('model')}")
    if not content and not judge:
        lines.append("- 本次 artifact 未包含内容/judge 报告（CI 未配置 EVAL_JUDGE_API_KEY 时按设计跳过）。")
    lines += ["", "## 3. 能声称 / 不能声称", ""]
    lines.append(f"- 能声称：流程完成率、失败率（带 CI）、target 归一交付、硬规则/安全/负向断言结果。")
    lines.append(f"- 不能声称：匹配质量、内容质量达标、泛化、优化有效"
                 + ("" if result["claims"]["quality_claim_allowed"] else "（缺少 E3 人工盲评）") + "。")
    if not result["claims"]["pass_k_stable"]:
        lines.append("- ⚠️ pass^k 不可作为稳定质量结论：存在 unstable/失败场景（同一冻结场景跨 run 差异明显）。")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="质量评分卡（artifact 汇总）")
    parser.add_argument("--run", action="append", default=[], type=Path,
                        help="live-eval / v4-pilot artifact 目录，可重复")
    parser.add_argument("--matrix", action="append", default=[], type=Path)
    parser.add_argument("--content", action="append", default=[], type=Path)
    parser.add_argument("--judge", action="append", default=[], type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    matrices = list(args.matrix)
    reports: list[Path] = []
    contents = list(args.content)
    judges = list(args.judge)
    for artifact in args.run:
        found = _discover(artifact)
        if found["matrix"]:
            matrices.append(found["matrix"])
        if found["report"]:
            reports.append(found["report"])
        if found["content"]:
            contents.append(found["content"])
        if found["judge"]:
            judges.append(found["judge"])
    if not matrices:
        raise SystemExit("没有 matrix 输入：用 --run 或 --matrix")
    result = build(matrices, reports, contents, judges)
    text = render(result)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"scenario_runs": result["summary"]["scenario_runs"],
                      "failures": result["summary"]["failures"],
                      "target_attainment": result["summary"]["target_attainment"],
                      "unstable": result["summary"]["unstable_scenarios"],
                      "claims": result["claims"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())