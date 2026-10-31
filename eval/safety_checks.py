#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匹配运行的安全/隐私检查（无模型、可离线跑）。

检查对象是 quality bundle 里的候选文本与运行总结：
- 手机号 / 邮箱 / 身份证号 / API Key：错误（阻断）；
- 承诺性措辞（保证、一定、绝对、承诺、100%）：warning；
- 提示词注入痕迹（忽略之前指令、ignore previous instructions、system prompt 等）：warning。

用法：
  python eval/safety_checks.py --bundle eval/fixtures/quality_bundle_sample.json
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PII_PATTERNS = {
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "id_card": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "secret": re.compile(r"(?:sk-[A-Za-z0-9]{10,}|api[_-]?key\s*[:=]\s*\S+)", re.I),
}
PROMISE = re.compile(r"保证|一定|绝对|承诺|100%|放心")
INJECTION = re.compile(r"忽略(?:之前|以上|前面).*?(?:指令|提示|要求)|ignore\s+(?:all\s+)?(?:previous|prior)?.{0,20}instructions|system\s*prompt|你现在是", re.I)
TEXT_FIELDS = ("self_intro", "roommate_expectation", "reject_reason", "summary")


def scan_text(text, field, run_id, candidate):
    findings = []
    body = str(text or "")
    if not body:
        return findings
    for kind, pattern in PII_PATTERNS.items():
        for match in pattern.finditer(body):
            findings.append({"kind": f"pii_{kind}", "severity": "error", "run_id": run_id,
                             "candidate": candidate, "field": field, "match": match.group(0)[:80]})
    if field in ("reject_reason", "summary"):
        for match in PROMISE.finditer(body):
            findings.append({"kind": "promise", "severity": "warning", "run_id": run_id,
                             "candidate": candidate, "field": field, "match": match.group(0)})
    if field in ("self_intro", "roommate_expectation"):
        for match in INJECTION.finditer(body):
            findings.append({"kind": "prompt_injection", "severity": "warning", "run_id": run_id,
                             "candidate": candidate, "field": field, "match": match.group(0)[:120]})
    return findings


def scan_bundle(bundle):
    findings = []
    for run in bundle.get("runs", []):
        run_id = (run.get("run") or {}).get("id")
        applicant = run.get("applicant") or {}
        for field in TEXT_FIELDS:
            findings += scan_text(applicant.get(field), f"applicant.{field}", run_id,
                                  applicant.get("nickname"))
        for candidate in run.get("candidates", []):
            for field in TEXT_FIELDS:
                findings += scan_text(candidate.get(field), f"candidate.{field}", run_id,
                                      candidate.get("nickname"))
                for moment in candidate.get("moments") or []:
                    findings += scan_text(moment.get("content"), "candidate.moment", run_id,
                                          candidate.get("nickname"))
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    findings = scan_bundle(bundle)
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    result = {"bundle": str(args.bundle), "findings": findings,
              "errors": len(errors), "warnings": len(warnings)}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 安全 / 隐私检查报告", "", f"- 数据包：`{args.bundle}`",
             f"- 错误：{len(errors)}；warning：{len(warnings)}", ""]
    if findings:
        lines += ["| 严重度 | 类型 | run | 候选 | 字段 | 命中 |", "|---|---|---|---|---|---|"]
        for item in findings:
            lines.append(f"| {item['severity']} | {item['kind']} | {item['run_id']} | "
                         f"{item['candidate'] or '—'} | {item['field']} | `{item['match']}` |")
    else:
        lines.append("未发现 PII、承诺性措辞或提示词注入痕迹。")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.json:
        print(f"JSON 报告：{args.json}")
    print(json.dumps({"errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
