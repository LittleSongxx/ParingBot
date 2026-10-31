#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""质量检查：对真实匹配运行的数据包做「硬规则 + 汇总一致性 + 证据覆盖」检查。

输入是 quality bundle（eval/build_quality_bundle.py 生成，或 analysis/quality-bundles/*.json）：
每个 run 含 applicant / candidates / funnel / run.summary / deliverable_passed_count 等。

输出：
- 每条交付候选的硬规则检查（同性、双方 must、计划租期档位差）；
- run summary 数字 vs 库内字段；
- 证据覆盖率（交付候选有画像/通过理由）；
- 截断透明度；
- JSON 报告 + Markdown 摘要；有硬错误 exit 1。

用法：
  python eval/quality_checks.py --bundle analysis/quality-bundles/runs-174-176.json
  python eval/quality_checks.py --bundle ... --json /tmp/checks.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

LEASE_TERMS = ("3个月以下", "3-6个月", "6-12个月", "1-2年", "2年以上")
TIDINESS_LEVELS = ("随意", "一般", "整洁", "洁癖")
SCHEDULE_TYPES = ("早睡早起", "正常作息", "夜猫子")
LEASE_GAP_LIMIT = 2


def _terms(text):
    return [item.strip() for item in str(text or "").replace("，", ",").split(",") if item.strip()]


def _age(birth, as_of):
    try:
        born = datetime.strptime(str(birth)[:10], "%Y-%m-%d").date()
        ref = as_of if isinstance(as_of, date) else date.today()
        return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))
    except (TypeError, ValueError):
        return None


def _rank(values, value):
    try:
        return values.index(value)
    except (ValueError, AttributeError):
        return None


def _must_dims(preference):
    return [key for key, value in (preference or {}).items()
            if key.endswith("_required") and value == "必须"]


def _has_constraint(preference, code):
    if code == "age":
        return preference.get("age_min") is not None and preference.get("age_max") is not None
    if code == "budget":
        return preference.get("budget_min") is not None and preference.get("budget_max") is not None
    if code == "tidiness":
        return preference.get("tidiness_min") not in (None, TIDINESS_LEVELS[0])
    if code == "store":
        return preference.get("store_scope") in ("同门店", "同片区")
    if code == "schedule":
        accepted = set(_terms(preference.get("schedule_accept")))
        return bool(accepted) and accepted != set(SCHEDULE_TYPES)
    if code == "lease":
        return preference.get("lease_min") not in (None, LEASE_TERMS[0])
    if code == "pet":
        return preference.get("pet_accept") == "不接受"
    return False


def _violates(applicant, candidate, preference, code, as_of):
    """申请方是否不满足候选方在 code 维度上的必须项。"""
    if code == "age":
        age = _age(applicant.get("birth_date"), as_of)
        if age is None:
            return False
        return age < preference["age_min"] or age > preference["age_max"]
    if code == "budget":
        value = applicant.get("rent_budget")
        return value is not None and (value < preference["budget_min"] or value > preference["budget_max"])
    if code == "tidiness":
        left = _rank(TIDINESS_LEVELS, applicant.get("tidiness"))
        right = _rank(TIDINESS_LEVELS, preference.get("tidiness_min"))
        return left is not None and right is not None and left < right
    if code == "store":
        scope = preference.get("store_scope")
        if scope == "同门店":
            return bool(applicant.get("store")) and applicant.get("store") != candidate.get("store")
        if scope == "同片区":
            return False  # 门店片区映射不在 bundle 里，交给人工/后端复核
        return False
    if code == "schedule":
        return bool(applicant.get("schedule_type")) and applicant.get("schedule_type") not in set(_terms(preference.get("schedule_accept")))
    if code == "lease":
        left = _rank(LEASE_TERMS, applicant.get("lease_term"))
        right = _rank(LEASE_TERMS, preference.get("lease_min"))
        return left is not None and right is not None and left < right
    if code == "pet":
        return preference.get("pet_accept") == "不接受" and applicant.get("has_pet") == "有"
    return False


def lease_gap(one, other):
    left, right = _rank(LEASE_TERMS, one), _rank(LEASE_TERMS, other)
    return None if left is None or right is None else abs(left - right)


def hard_problems(applicant, candidate, as_of):
    preference = candidate.get("preference") or {}
    problems = []
    if applicant.get("gender") and candidate.get("gender") and applicant["gender"] != candidate["gender"]:
        problems.append("同性规则：性别不同")
    for code in _must_dims(preference):
        if not _has_constraint(preference, code):
            continue
        if _violates(applicant, candidate, preference, code, as_of):
            problems.append(f"候选方必须项「{code}」不满足")
    reverse = applicant.get("preference") or {}
    for code in _must_dims(reverse):
        if not _has_constraint(reverse, code):
            continue
        if _violates(candidate, applicant, reverse, code, as_of):
            problems.append(f"申请方必须项「{code}」候选方不满足")
    gap = lease_gap(applicant.get("lease_term"), candidate.get("lease_term"))
    if gap is not None and gap >= LEASE_GAP_LIMIT:
        problems.append(f"计划租期档位差 {gap} 档（{applicant.get('lease_term')} vs {candidate.get('lease_term')}）")
    return problems


def parse_summary(summary):
    patterns = {
        "rounds": r"调度\s*(\d+)\s*轮",
        "total": r"候选池累计\s*(\d+)\s*人",
        "passed": r"通过审核\s*(\d+)\s*人",
        "rejected": r"否决\s*(\d+)\s*人",
        "delivered": r"交付\s*(\d+)\s*人",
    }
    return {key: int(match.group(1)) if (match := re.search(pattern, summary or "")) else None
            for key, pattern in patterns.items()}


def check_run(run_bundle):
    run = run_bundle.get("run") or {}
    task = run_bundle.get("task") or {}
    applicant = run_bundle.get("applicant") or {}
    candidates = run_bundle.get("candidates") or []
    delivered = [row for row in candidates if row.get("delivered")]
    as_of = None
    try:
        as_of = datetime.strptime(str(run.get("end") or run.get("start") or "")[:19], "%Y-%m-%d %H:%M:%S").date()
    except (TypeError, ValueError):
        pass
    violations = []
    for candidate in delivered:
        problems = hard_problems(applicant, candidate, as_of)
        if problems:
            violations.append({"candidate": candidate.get("nickname"), "candidate_id": candidate.get("id"),
                               "problems": problems})
    summary_numbers = parse_summary(run.get("summary"))
    funnel = run_bundle.get("funnel") or {}
    stages = {stage.get("key"): stage.get("value") for stage in (funnel.get("stages") or [])}
    counts = {
        "candidates": len(candidates),
        "delivered_flag": len(delivered),
        "passed_flag": sum(1 for row in candidates if row.get("audit_status") == "通过"),
        "rejected_flag": sum(1 for row in candidates if row.get("audit_status") == "否决"),
        "funnel_total": stages.get("total"),
        "funnel_passed": stages.get("passed"),
        "funnel_rejected": stages.get("rejected"),
        "funnel_delivered": stages.get("delivered"),
        "deliverable_passed": run_bundle.get("deliverable_passed_count"),
        "delivered_to_user": run_bundle.get("delivered_to_user"),
        "task_deliver_count": task.get("deliver_count"),
    }
    summary_errors = []
    # 「交付」在总结里说的是页面实际交付数：通过名单可能大于 deliver_count，
    # 不能拿 delivered_flag（通过人数）直接比，否则 9 通过/8 展示会被误报。
    summary_fields = {"total": "candidates", "passed": "passed_flag",
                      "rejected": "rejected_flag", "delivered": "delivered_to_user"}
    for key, field in summary_fields.items():
        value = summary_numbers.get(key)
        if value is not None and counts[field] is not None and value != counts[field]:
            summary_errors.append(f"summary {key}={value}，库内 {field}={counts[field]}")
    if summary_numbers.get("rounds") is not None and run.get("total_round") is not None \
            and summary_numbers["rounds"] != run["total_round"]:
        summary_errors.append(f"summary rounds={summary_numbers['rounds']}，库内 total_round={run['total_round']}")
    evidence_missing = [row for row in delivered if not (row.get("portrait") or row.get("evidence"))]
    # 新版交付总结会在截断时写「未展示的候选」；旧 bundle 没有这句，按未记录处理
    truncation_recorded = "未展示的候选" in str(run.get("summary") or "")
    truncation_unrecorded = ((counts["deliverable_passed"] or 0) > (counts["delivered_to_user"] or 0)
                             and not truncation_recorded)
    errors = []
    if violations:
        errors.append(f"{len(violations)} 条交付候选违反硬规则")
    if summary_errors:
        errors.extend(summary_errors)
    return {
        "run_id": run.get("id"), "run_no": run.get("run_no"),
        "status": run.get("status"), "summary": run.get("summary"),
        "counts": counts, "summary_numbers": summary_numbers,
        "summary_errors": summary_errors,
        "hard_rule_violations": violations,
        "evidence": {"delivered": len(delivered),
                     "with_portrait": len(delivered) - len(evidence_missing),
                     "with_evidence": sum(1 for row in delivered
                                          if row.get("portrait") or row.get("evidence")),
                     "missing_portrait": len(evidence_missing)},
        "shortfall": {"requested": counts["task_deliver_count"],
                      "delivered": counts["delivered_to_user"],
                      "partial": bool(counts["task_deliver_count"] and counts["delivered_to_user"] is not None
                                      and counts["delivered_to_user"] < counts["task_deliver_count"])},
        "truncation": {"passed": counts["deliverable_passed"], "delivered_to_user": counts["delivered_to_user"],
                        "unrecorded": truncation_unrecorded},
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path, help="Markdown 报告路径")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    runs = [check_run(item) for item in bundle.get("runs", [])]
    total_errors = [error for run in runs for error in run["errors"]]
    print(f"检查 {len(runs)} 个 run")
    for run in runs:
        print(f"- run {run['run_id']}: status={run['status']} 交付时/展示="
              f"{run['counts']['deliverable_passed']}/{run['counts']['delivered_to_user']} "
              f"硬规则违规={len(run['hard_rule_violations'])} "
              f"summary不一致={len(run['summary_errors'])} "
              f"无画像={run['evidence']['missing_portrait']}/{run['evidence']['delivered']}")
        for item in run["hard_rule_violations"]:
            print(f"    [HARD] {item['candidate']}: {'；'.join(item['problems'])}")
        for error in run["summary_errors"]:
            print(f"    [SUMMARY] {error}")
    payload = {"bundle": args.bundle, "runs": runs, "errors": total_errors}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告：{args.json}")
    if args.out:
        lines = ["# 质量检查报告", "", f"数据包：`{args.bundle}`", "", "## 总览", "",
                 "| run | 状态 | 交付时/展示 | 硬规则违规 | summary 不一致 | 有证据/交付 |",
                 "|---|---|---|---|---|---|"]
        for run in runs:
            lines.append(f"| {run['run_id']} | {run['status']} | "
                         f"{run['counts']['deliverable_passed']}/{run['counts']['delivered_to_user']} | "
                         f"{len(run['hard_rule_violations'])} | {len(run['summary_errors'])} | "
                         f"{run['evidence']['with_evidence']}/{run['evidence']['delivered']} |")
            if run["hard_rule_violations"] or run["summary_errors"]:
                lines += ["", "### 问题", ""]
                lines += [f"- 硬规则：{item['candidate']}：{'；'.join(item['problems'])}"
                          for item in run["hard_rule_violations"]]
                lines += [f"- summary：{error}" for error in run["summary_errors"]]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Markdown 报告：{args.out}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
