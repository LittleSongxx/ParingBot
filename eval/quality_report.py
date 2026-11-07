"""质量报告聚合器：把 6 项指标 artifact + 人工校准合成一份可追溯报告。

用法：
    python eval/quality_report.py \
      --pairwise quality-pairwise.json \
      --false-reject false-reject.json \
      --recall delivery-recall.json \
      --content content-faithfulness.json \
      --pass-k pass-k.json \
      --safety safety.json \
      --calibration judge-calibration.json \
      --acceptance signoff.json \
      --out-md quality-report.md --out-json quality-report.json

报告是唯一对外口径：每行指标都必须带 n / CI / 证据级 / judge 版本，
质量类指标只有 claims.quality_claim_allowed=true 时才允许写"匹配质量"结论。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import stats  # noqa: E402
import quality_spec as spec  # noqa: E402

METRIC_KEYS = spec.ORDER


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _code_commit(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT.parent), text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _fmt_pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{100 * float(value):.1f}%"


def _fmt_kappa(value) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def _fmt_ci(bucket) -> str:
    if not bucket or bucket.get("lo") is None:
        return "n/a"
    return f"95%CI {_fmt_pct(bucket['lo'])}–{_fmt_pct(bucket['hi'])}"


def _summary_row(key: str, payload: dict | None) -> dict:
    """每个指标一行摘要（值/n/CI/证据级/结论）。"""
    metric = spec.get(key)
    row = {"key": key, "name": metric.name_zh, "evidence": metric.evidence,
           "value": "未测", "n": "-", "ci": "-", "note": ""}
    if not payload:
        return row
    if key == "match_quality":
        strict = payload.get("strict_win_rate")
        rate = strict if strict is not None else payload.get("win_rate")
        ci = payload.get("strict_win_rate_ci95") or payload.get("win_rate_ci95")
        row["value"] = _fmt_pct(rate)
        row["n"] = str(payload.get("n_pairs_judged") or payload.get("n_pairs") or "-")
        row["ci"] = _fmt_ci(ci)
        by = payload.get("by_stratum") or {}

        def _block_rate(block):
            block = block or {}
            value = block.get("strict_win_rate")
            return value if value is not None else block.get("win_rate")

        detail = ", ".join(f"{name}={_fmt_pct(_block_rate(block))}"
                           for name, block in by.items())
        row["note"] = ("strict（剔除 tie/未决）"
                       + (f"; tie={_fmt_pct(payload.get('tie_rate'))}"
                          if payload.get("tie_rate") is not None else "")
                       + (f"; {detail}" if detail else "")
                       + (f"; position={payload.get('position_consistency')}"
                          if payload.get("position_consistency") is not None else ""))
    elif key == "false_reject":
        hard = (payload.get("hard") or {}).get("rate")
        soft = (payload.get("soft") or {}).get("rate")
        row["value"] = f"硬假否决 {_fmt_pct(hard)} / 软误拒 {_fmt_pct(soft)}"
        row["n"] = (f"hard={int((payload.get('hard') or {}).get('n') or 0)}, "
                    f"soft={int((payload.get('soft') or {}).get('n') or 0)}")
        row["ci"] = _fmt_ci((payload.get("soft") or {}).get("ci95"))
        row["note"] = f"假通过={(payload.get('false_pass') or {}).get('count')}"
    elif key == "delivery_recall":
        row["value"] = _fmt_pct(payload.get("mean_attainment"))
        row["n"] = f"{payload.get('n_scenarios', '-')} 场景"
        row["ci"] = _fmt_ci(payload.get("attainment_ci95"))
        row["note"] = f"交付精度={_fmt_pct(payload.get('mean_precision'))}"
    elif key == "content_faithfulness":
        row["value"] = _fmt_pct(payload.get("faithful_rate"))
        row["n"] = f"{payload.get('n_claims', 0)} claims / {payload.get('n_items', 0)} items"
        row["ci"] = _fmt_ci(payload.get("faithful_ci95"))
        row["note"] = (f"矛盾率={_fmt_pct(payload.get('contradiction_rate'))}; "
                       f"证据覆盖={_fmt_pct(payload.get('evidence_coverage'))}")
    elif key == "pass_k":
        row["value"] = f"pass^{payload.get('k')}={_fmt_pct(payload.get('pass_k'))}, pass^1={_fmt_pct(payload.get('pass_1'))}"
        row["n"] = f"{payload.get('n_scenarios', '-')} 场景 × {payload.get('n_trials', '-')} trials"
        row["ci"] = _fmt_ci(payload.get("pass_k_ci95"))
    elif key == "safety":
        negative = payload.get("negative_assertions") or {}
        injection = payload.get("injection") or {}
        row["value"] = (f"硬违规={payload.get('hard_rule_violations', 'n/a')}, "
                        f"负向={negative.get('passed', 'n/a')}/{negative.get('total', 'n/a')}, "
                        f"注入={_fmt_pct(injection.get('success_rate'))}")
        row["n"] = f"注入 {injection.get('attempts', 0)} 例"
    return row


def _calibration_items(calibration) -> list[dict]:
    if not calibration or not isinstance(calibration, dict):
        return []
    if "metric" in calibration:
        return [calibration]
    return [value for value in calibration.values() if isinstance(value, dict)]


def build(metric_payloads: dict, calibration: dict | None, meta: dict | None = None,
          acceptance: dict | None = None) -> dict:
    meta = meta or {}
    metrics = {}
    for key, payload in (metric_payloads or {}).items():
        if key not in spec.METRICS:
            raise KeyError(f"未知指标 {key}；可用：{', '.join(METRIC_KEYS)}")
        metrics[key] = payload
    claims = spec.evaluate_claims(metrics, calibration)
    calibrations = _calibration_items(calibration)
    calibration_reasons = [reason for item in calibrations for reason in (item.get("reasons") or [])]
    report = {
        "protocol": spec.PROTOCOL_VERSION,
        "judge_version": spec.JUDGE_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "code_commit": meta.get("code_commit") or _code_commit(None),
        "dataset": meta.get("dataset") or {
            "profile": "eval",
            "frozen": "v3/v4（见 artifact 元数据）",
        },
        "judge": {
            "version": spec.JUDGE_VERSION,
            "calibration_count": len(calibrations),
            "calibration_usable": bool(calibrations) and all(
                bool(item.get("usable")) for item in calibrations),
            "calibration_reasons": calibration_reasons,
        },
        "metrics": metrics,
        "rows": [_summary_row(key, metrics.get(key)) for key in METRIC_KEYS],
        "calibration": calibration,
        "human_acceptance": acceptance,
        "claims": claims,
        "provenance": meta.get("provenance") or {},
    }
    return report


def render(report: dict) -> str:
    lines: list[str] = []
    lines.append("# 质量报告（quality-v1）")
    lines.append("")
    lines.append(f"> protocol `{report.get('protocol')}` · judge `{report.get('judge_version')}` "
                 f"· code `{(report.get('code_commit') or 'unknown')[:12]}` · "
                 f"生成 {report.get('generated_at')}")
    lines.append("")
    quality_ok = bool((report.get("claims") or {}).get("quality_claim_allowed"))
    lines.append("## 0. 一页结论")
    lines.append("")
    lines.append(f"- **质量类结论（匹配质量/内容/误拒）：{'✅ 可申报' if quality_ok else '⛔ 不可申报'}**")
    calibration_items = _calibration_items(report.get("calibration"))
    if calibration_items:
        for item in calibration_items:
            lines.append(f"- 人工校准[{item.get('metric')}]：n={item.get('n_labeled')}，"
                         f"judge-human kappa={_fmt_pct((item.get('judge_human') or {}).get('kappa'))}，"
                         f"位置一致性={item.get('position_consistency')}，"
                         f"usable={str(bool(item.get('usable'))).lower()}")
            ppi = item.get("ppi") or {}
            if ppi.get("available"):
                lines.append(f"  - PPI 校正后胜率：{_fmt_pct(ppi.get('corrected_rate'))}"
                             f"（原始 judge {_fmt_pct(ppi.get('raw_judge_rate'))}，"
                             f"{_fmt_ci({'lo': ppi.get('lo'), 'hi': ppi.get('hi')})}）")
    else:
        lines.append("- 人工校准：无（质量类指标 blocked）")
    acceptance = report.get("human_acceptance") or {}
    if acceptance:
        lines.append(f"- 人工验收：{acceptance.get('note') or acceptance.get('usable')}")
    lines.append("")
    lines.append("## 1. 六项指标")
    lines.append("")
    lines.append("| 指标 | 值 | n | 区间/备注 | 证据级 |")
    lines.append("|---|---|---|---|---|")
    for row in report.get("rows") or []:
        note = row.get("note") or ""
        ci = row.get("ci") if row.get("ci") not in ("-", "n/a") else ""
        extra = "；".join(part for part in (ci, note) if part) or "—"
        lines.append(f"| {row['name']} | {row['value']} | {row['n']} | {extra} | {row['evidence']} |")
    lines.append("")
    lines.append("## 2. 申报门禁")
    lines.append("")
    lines.append(spec.render_claim_table(report.get("claims") or {"per_metric": {}}))
    lines.append("")
    lines.append("## 3. 口径与复现")
    lines.append("")
    lines.append("- 统计：比例用 Wilson/Clopper-Pearson；跨 run 按场景 cluster bootstrap；"
                 "judge 分数经人工校准后 PPI 校正。")
    lines.append("- 禁止：无人工校准时把 judge 分数当质量结论；把同场景 trial 当独立样本；"
                 "跨协议/跨数据集横比。")
    lines.append(f"- 数据集：`{json.dumps(report.get('dataset'), ensure_ascii=False)}`")
    provenance = report.get("provenance") or {}
    if provenance:
        lines.append("- artifact：")
        for key, path in provenance.items():
            lines.append(f"  - {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="聚合 6 项质量指标为统一报告")
    parser.add_argument("--pairwise", type=Path)
    parser.add_argument("--false-reject", type=Path)
    parser.add_argument("--recall", type=Path)
    parser.add_argument("--content", type=Path)
    parser.add_argument("--pass-k", type=Path)
    parser.add_argument("--safety", type=Path)
    parser.add_argument("--calibration", type=Path, action="append",
                        help="judge 校准 JSON（可重复：每个指标一个；或一个 {metric: calib} 映射）")
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--dataset-note", default=None)
    args = parser.parse_args(argv)

    paths = {
        "match_quality": args.pairwise,
        "false_reject": args.false_reject,
        "delivery_recall": args.recall,
        "content_faithfulness": args.content,
        "pass_k": args.pass_k,
        "safety": args.safety,
    }
    payloads = {}
    provenance = {}
    for key, path in paths.items():
        if path and Path(path).exists():
            payloads[key] = read_json(path)
            provenance[key] = str(path)
    calibration = None
    if args.calibration:
        merged: dict = {}
        single = None
        for path in args.calibration:
            if not path or not Path(path).exists():
                continue
            data = read_json(path)
            provenance[f"calibration:{Path(path).name}"] = str(path)
            if isinstance(data, dict) and "metric" in data:
                merged[str(data["metric"])] = data
                single = data
            elif isinstance(data, dict):
                merged.update({key: value for key, value in data.items()
                               if isinstance(value, dict)})
        if len(merged) > 1:
            calibration = merged
        elif single is not None:
            calibration = single
        elif merged:
            calibration = next(iter(merged.values()))
    acceptance = read_json(args.acceptance) if args.acceptance and Path(args.acceptance).exists() else None
    meta = {"code_commit": _code_commit(args.code_commit),
            "dataset": {"note": args.dataset_note} if args.dataset_note else None,
            "provenance": provenance}
    report = build(payloads, calibration, meta, acceptance)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(render(report), encoding="utf-8")
    print(json.dumps({"quality_claim_allowed": report["claims"]["quality_claim_allowed"],
                      "metrics": sorted(payloads),
                      "out_md": str(args.out_md), "out_json": str(args.out_json)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
