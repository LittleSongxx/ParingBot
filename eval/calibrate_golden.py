#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Golden 三评分器交叉校准（无需人工）。

A：heuristic-v4 gold（matching_labels.json）
B：作息/租期优先的独立权重
C：合住摩擦风险优先（作息/租期/宠物/吸烟）
共识：A(权重2)+B+C 的 Borda 前 8，输出 consensus labels 供回归使用。

用法：
  python eval/calibrate_golden.py --bundle analysis/quality-bundles/expanded-latest.json \
      --consensus-out eval/golden/consensus_labels.json
"""
from __future__ import annotations
import argparse, json
from datetime import date, datetime
from pathlib import Path

LEASE_TERMS = ("3个月以下", "3-6个月", "6-12个月", "1-2年", "2年以上")
TIDINESS = ("随意", "一般", "整洁", "洁癖")


def term_gap(a, b):
    try:
        return abs(LEASE_TERMS.index(a) - LEASE_TERMS.index(b))
    except (ValueError, AttributeError):
        return None


def age_of(birth, as_of):
    try:
        b = datetime.strptime(str(birth)[:10], "%Y-%m-%d").date()
        return as_of.year - b.year - ((as_of.month, as_of.day) < (b.month, b.day))
    except Exception:
        return None


def split(v):
    return [x.strip() for x in str(v or "").replace("，", ",").split(",") if x.strip()]


def hard_ok(app, cand):
    if app.get("gender") and cand.get("gender") and app["gender"] != cand["gender"]:
        return False
    gap = term_gap(app.get("lease_term"), cand.get("lease_term"))
    if gap is not None and gap >= 2:
        return False
    pref = cand.get("preference") or {}
    if str(pref.get("age_required")) == "必须":
        age = age_of(app.get("birth_date"), date.today())
        try:
            if age is None or age < int(pref["age_min"]) or age > int(pref["age_max"]):
                return False
        except (TypeError, ValueError):
            pass
    if str(pref.get("budget_required")) == "必须":
        value = app.get("rent_budget")
        try:
            if value is not None and (value < int(pref["budget_min"]) or value > int(pref["budget_max"])):
                return False
        except (TypeError, ValueError):
            pass
    if str(pref.get("store_required")) == "必须" and pref.get("store_scope") == "同门店":
        if app.get("store") and cand.get("store") and app["store"] != cand["store"]:
            return False
    if str(pref.get("schedule_required")) == "必须" and app.get("schedule_type"):
        if app["schedule_type"] not in split(pref.get("schedule_accept")):
            return False
    if str(pref.get("lease_required")) == "必须" and pref.get("lease_min"):
        try:
            if LEASE_TERMS.index(app.get("lease_term")) < LEASE_TERMS.index(pref.get("lease_min")):
                return False
        except (ValueError, AttributeError):
            pass
    if str(pref.get("pet_required")) == "必须" and pref.get("pet_accept") == "不接受" and app.get("has_pet") == "有":
        return False
    return True


def score_b(app, cand):
    s = 0.0
    gap = term_gap(app.get("lease_term"), cand.get("lease_term"))
    if gap == 0:
        s += 3
    elif gap == 1:
        s += 1
    pref = app.get("preference") or {}
    if cand.get("schedule_type") and cand["schedule_type"] in split(pref.get("schedule_accept")):
        s += 3
    if cand.get("store") and app.get("store") and cand["store"] == app["store"]:
        s += 2
    elif cand.get("area") and app.get("area") and cand["area"] == app["area"]:
        s += 1
    try:
        if cand.get("rent_budget") is not None and int(pref.get("budget_min")) <= cand["rent_budget"] <= int(pref.get("budget_max")):
            s += 2
    except (TypeError, ValueError):
        pass
    try:
        if cand.get("age") is not None and int(pref.get("age_min")) <= cand["age"] <= int(pref.get("age_max")):
            s += 1
    except (TypeError, ValueError):
        pass
    if cand.get("tidiness") in TIDINESS and pref.get("tidiness_min") in TIDINESS:
        if TIDINESS.index(cand["tidiness"]) >= TIDINESS.index(pref["tidiness_min"]):
            s += 1
    if set(split(app.get("interest_tags"))) & set(split(cand.get("interest_tags"))):
        s += 0.5
    if cand.get("portrait"):
        s += 0.5
    return s


def score_c(app, cand):
    s = 0.0
    pref = app.get("preference") or {}
    if cand.get("schedule_type") and cand["schedule_type"] in split(pref.get("schedule_accept")):
        s += 2
    gap = term_gap(app.get("lease_term"), cand.get("lease_term"))
    if gap == 0:
        s += 2
    elif gap == 1:
        s += 0.5
    if cand.get("has_pet") == "有" and pref.get("pet_accept") == "不接受":
        s -= 2
    if cand.get("smoking") in ("偶尔", "经常") and app.get("smoking") == "不吸烟":
        s -= 1
    if cand.get("store") and app.get("store") and cand["store"] == app["store"]:
        s += 1
    try:
        if cand.get("rent_budget") is not None and int(pref.get("budget_min")) <= cand["rent_budget"] <= int(pref.get("budget_max")):
            s += 2
    except (TypeError, ValueError):
        pass
    if cand.get("tidiness") in TIDINESS and pref.get("tidiness_min") in TIDINESS:
        if TIDINESS.index(cand["tidiness"]) >= TIDINESS.index(pref["tidiness_min"]):
            s += 1
    try:
        if cand.get("age") is not None and int(pref.get("age_min")) <= cand["age"] <= int(pref.get("age_max")):
            s += 1
    except (TypeError, ValueError):
        pass
    if cand.get("evidence"):
        s += 0.5
    return s


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--labels", type=Path, default=Path("eval/golden/matching_labels.json"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--consensus-out", type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    by_member = {}
    by_username = {}
    for item in labels.get("labels", []):
        by_member[item["member_id"]] = item
        if item.get("username"):
            by_username[item["username"]] = item
    rows = []
    consensus_labels = []
    for run in bundle.get("runs", []):
        app = run.get("applicant") or {}
        gold = by_member.get(app.get("id")) or by_username.get(app.get("username"))
        if not gold:
            continue
        candidates = [c for c in run.get("candidates", []) if c.get("gender") and hard_ok(app, c)]
        ranked_b = sorted(candidates, key=lambda c: (-score_b(app, c), c.get("id") or 0))[:8]
        ranked_c = sorted(candidates, key=lambda c: (-score_c(app, c), c.get("id") or 0))[:8]
        a_ids = set(gold.get("gold_ids") or [])
        b_ids = {c.get("id") for c in ranked_b}
        c_ids = {c.get("id") for c in ranked_c}
        scores = {}
        for weight, ids in ((2, a_ids), (1, b_ids), (1, c_ids)):
            for rank, candidate_id in enumerate(sorted(ids)):
                scores[candidate_id] = scores.get(candidate_id, 0) + weight * (9 - rank)
        consensus = [cid for cid, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))][:8]
        rows.append({
            "run_id": run.get("run", {}).get("id"),
            "applicant": app.get("nickname"),
            "a": sorted(a_ids), "b": sorted(b_ids), "c": sorted(c_ids),
            "consensus": consensus,
            "overlap": len(a_ids & b_ids),
            "jaccard": round(len(a_ids & b_ids) / len(a_ids | b_ids), 4) if a_ids | b_ids else 0.0,
            "consensus_overlap": len(a_ids & set(consensus)),
            "identical": a_ids == b_ids,
        })
        consensus_labels.append({
            "member_id": app.get("id"),
            "username": gold.get("username"),
            "nickname": app.get("nickname"),
            "gold_ids": consensus,
            "confidence": len(a_ids & set(consensus)),
        })
    valid = [row for row in rows if not row.get("skipped")]
    aggregate = {
        "runs": len(valid),
        "avg_overlap": round(sum(r["overlap"] for r in valid) / len(valid), 2) if valid else 0,
        "avg_jaccard": round(sum(r["jaccard"] for r in valid) / len(valid), 4) if valid else 0,
        "identical": sum(1 for r in valid if r["identical"]),
        "avg_consensus_overlap": round(sum(r["consensus_overlap"] for r in valid) / len(valid), 2) if valid else 0,
    }
    result = {"bundle": str(args.bundle), "labels": str(args.labels), "rows": rows, "aggregate": aggregate}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.consensus_out:
        payload = {
            "version": 1, "method": "consensus-borda-v1",
            "note": "A=heuristic-v4、B=作息/租期优先、C=摩擦风险优先；Borda 选前8，交叉校准生成，非人工真值",
            "labels": consensus_labels,
        }
        args.consensus_out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Golden 三评分器 / 共识校准", "", f"- 数据包：`{args.bundle}`",
             "- 评分器 A：heuristic-v4；B：作息/租期优先；C：摩擦风险优先；共识：A(权重2)+B+C 的 Borda 前8", "",
             "| run | 申请人 | A/B 一致 | top8 重合 | Jaccard | A∩共识 |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['run_id']} | {row['applicant']} | {'是' if row['identical'] else '否'} | "
                     f"{row['overlap']}/8 | {row['jaccard']:.2%} | {row['consensus_overlap']}/8 |")
    lines += ["", f"平均 A/B top8 重合：**{aggregate['avg_overlap']}/8**；平均 Jaccard：**{aggregate['avg_jaccard']:.2%}**；"
                  f"A/B 完全一致 {aggregate['identical']}/{aggregate['runs']}；A∩共识平均 **{aggregate['avg_consensus_overlap']}/8**。",
              "", "共识 gold 用于回归比单评分器稳，但仍不是人工真值。"]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
