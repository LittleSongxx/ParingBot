#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Golden 双评分器交叉校准（无需人工）。

评分器 A：生成 matching_labels.json 的 heuristic（门店/作息/预算/整洁/租期/兴趣）。
评分器 B：独立权重（作息、租期优先，弱化门店与兴趣），对同一批候选人重排 top8。
输出两位评分器 top8 的重合度、Jaccard、完全相同的人数，用来判断 heuristic gold 是否稳定。

用法：
  python eval/calibrate_golden.py --bundle analysis/quality-bundles/expanded-latest.json
"""
from __future__ import annotations
import argparse, json
from datetime import date, datetime
from pathlib import Path

LEASE_TERMS=("3个月以下","3-6个月","6-12个月","1-2年","2年以上")
TIDINESS=("随意","一般","整洁","洁癖")

def term_gap(a,b):
    try:return abs(LEASE_TERMS.index(a)-LEASE_TERMS.index(b))
    except (ValueError,AttributeError):return None

def age_of(birth,as_of):
    try:
        b=datetime.strptime(str(birth)[:10],"%Y-%m-%d").date()
        return as_of.year-b.year-((as_of.month,as_of.day)<(b.month,b.day))
    except Exception:return None

def split(v): return [x.strip() for x in str(v or "").replace("，",",").split(",") if x.strip()]

def hard_ok(app,cand):
    """只做粗硬条件：同性 + 租期档位 + 双方必须项（值转数字/字符串）。"""
    if app.get("gender") and cand.get("gender") and app["gender"]!=cand["gender"]:return False
    gap=term_gap(app.get("lease_term"),cand.get("lease_term"))
    if gap is not None and gap>=2:return False
    pref=cand.get("preference") or {}
    # 候选人必须项：申请方是否满足
    if str(pref.get("age_required"))=="必须":
        age=age_of(app.get("birth_date"),date.today())
        try:
            if age is None or age<int(pref["age_min"]) or age>int(pref["age_max"]):return False
        except (TypeError,ValueError):pass
    if str(pref.get("budget_required"))=="必须":
        v=app.get("rent_budget")
        try:
            if v is not None and (v<int(pref["budget_min"]) or v>int(pref["budget_max"])):return False
        except (TypeError,ValueError):pass
    if str(pref.get("store_required"))=="必须" and pref.get("store_scope")=="同门店":
        if app.get("store") and cand.get("store") and app["store"]!=cand["store"]:return False
    if str(pref.get("schedule_required"))=="必须" and app.get("schedule_type"):
        if app["schedule_type"] not in split(pref.get("schedule_accept")):return False
    if str(pref.get("lease_required"))=="必须" and pref.get("lease_min"):
        gap=term_gap(app.get("lease_term"),pref.get("lease_min"))
        if gap is not None and term_gap(app.get("lease_term"),pref.get("lease_min")) is None:return False
        try:
            if LEASE_TERMS.index(app.get("lease_term"))<LEASE_TERMS.index(pref.get("lease_min")):return False
        except (ValueError,AttributeError):pass
    if str(pref.get("pet_required"))=="必须" and pref.get("pet_accept")=="不接受" and app.get("has_pet")=="有":
        return False
    return True

def score_b(app,cand):
    s=0.0
    gap=term_gap(app.get("lease_term"),cand.get("lease_term"))
    if gap==0:s+=3
    elif gap==1:s+=1
    if cand.get("schedule_type") and cand["schedule_type"] in split((app.get("preference") or {}).get("schedule_accept")):
        s+=3
    if cand.get("store") and app.get("store") and cand["store"]==app["store"]:s+=2
    elif cand.get("area") and app.get("area") and cand["area"]==app["area"]:s+=1
    pref=app.get("preference") or {}
    try:
        if cand.get("rent_budget") is not None and int(pref.get("budget_min"))<=cand["rent_budget"]<=int(pref.get("budget_max")):s+=2
    except (TypeError,ValueError):pass
    try:
        if cand.get("age") is not None and int(pref.get("age_min"))<=cand["age"]<=int(pref.get("age_max")):s+=1
    except (TypeError,ValueError):pass
    if cand.get("tidiness") in TIDINESS and pref.get("tidiness_min") in TIDINESS:
        if TIDINESS.index(cand["tidiness"])>=TIDINESS.index(pref["tidiness_min"]):s+=1
    ai=set(split(app.get("interest_tags"))); ci=set(split(cand.get("interest_tags")))
    if ai&ci:s+=0.5
    if cand.get("portrait"):s+=0.5
    return s

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--bundle",required=True,type=Path);ap.add_argument("--labels",type=Path,default=Path("eval/golden/matching_labels.json"));ap.add_argument("--json",type=Path);ap.add_argument("--out",type=Path)
    args=ap.parse_args()
    bundle=json.loads(args.bundle.read_text(encoding="utf-8")); labels=json.loads(args.labels.read_text(encoding="utf-8"))
    by={x["member_id"]:x for x in labels["labels"]}; rows=[]
    for run in bundle.get("runs",[]):
        app=run.get("applicant") or {}; gold=by.get(app.get("id"))
        if not gold: continue
        cands=[c for c in run.get("candidates",[]) if c.get("gender") and hard_ok(app,c)]
        ranked=sorted(cands,key=lambda c:(-score_b(app,c),c.get("id") or 0))[:8]
        b_ids={c.get("id") for c in ranked}; a_ids=set(gold.get("gold_ids") or [])
        rows.append({"run_id":run.get("run",{}).get("id"),"applicant":app.get("nickname"),
                     "a":sorted(a_ids),"b":sorted(b_ids),"overlap":len(a_ids&b_ids),
                     "jaccard":round(len(a_ids&b_ids)/len(a_ids|b_ids),4) if a_ids|b_ids else 0.0,
                     "identical":a_ids==b_ids})
    valid=[r for r in rows if not r.get("skipped")]
    agg={"runs":len(valid),"avg_overlap":round(sum(r["overlap"] for r in valid)/len(valid),2) if valid else 0,"avg_jaccard":round(sum(r["jaccard"] for r in valid)/len(valid),4) if valid else 0,"identical":sum(1 for r in valid if r["identical"])}
    result={"bundle":str(args.bundle),"labels":str(args.labels),"rows":rows,"aggregate":agg}
    if args.json:
        args.json.write_text(json.dumps(result,ensure_ascii=False,indent=1),encoding="utf-8")
    lines=["# Golden 双评分器交叉校准","",f"- 数据包：`{args.bundle}`",f"- 评分器 A：heuristic-v4 gold；评分器 B：作息/租期优先的独立权重","",
           "| run | 申请人 | 完全一致 | top8 重合 | Jaccard |","|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['run_id']} | {r['applicant']} | {'是' if r['identical'] else '否'} | {r['overlap']}/8 | {r['jaccard']:.2%} |")
    lines+=["",f"平均 top8 重合：**{agg['avg_overlap']}/8**；平均 Jaccard：**{agg['avg_jaccard']:.2%}**；完全一致 {agg['identical']}/{agg['runs']} 个 run。","","重合度低不代表谁错，表示 heuristic 的排序不稳定，gold 只能作为可重复基线，不能当人工真值。"]
    if args.out:args.out.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(agg,ensure_ascii=False))
    return 0
if __name__=="__main__":raise SystemExit(main())
