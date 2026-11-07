#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付名单内部成对评审：排名最高的候选 vs 排名最低的候选，哪个更适合。

审计修正（2026-11-05，A3）：
* 送 judge 的 applicant/candidate 材料全部走 pairwise_quality.safe_person() 白名单 ——
  delivered_rank/screen_score/delivered/audit_status/evidence 等系统元数据不再进入 prompt；
* forward/backward payload 构造完成后过 assert_safe_material()（fail-closed），
  角色/排名信息只保留在内部映射与输出 JSON 的审计字段里；
* 输出增加 meta（bundle meta / mode / limit / pair 数）与 Wilson 95% CI；
  每行 rank_a/rank_b 只放审计字段（candidate_id / delivered_rank），不放原始 candidate。

用来检验系统交付排序（delivered_rank）是否与独立 judge 的偏好一致；
A/B 位置交换，报告 top 胜率与 position consistency。
仍是 LLM 代理评审，不是人工真值。

用法：
  python eval/pairwise_ranking.py --bundle quality-bundle.json --env-file .env.eval \
      --out ranking-report.md --json ranking-report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from pairwise_quality import (  # noqa: E402
    assert_safe_material,
    call,
    load_env,
    safe_person,
    wilson_ci,
)

RUBRIC = """你是独立盲评员。同一申请方有 A/B 两位候选，请判断谁更适合合租。
先分别核对硬条件（同性/双向必须项/租期档差）和生活习惯（作息/吸烟/宠物/整洁），再比较。
A/B 的位置不代表优劣，不要因为 A 在前就选 A；接近时选 tie。
只输出 JSON 数组，对象字段 pair_id, winner（A/B/tie）, reason（<=40字）。不要 markdown。
"""

# 输出 JSON 里允许出现的候选审计字段（只用于事后核查，不进 prompt）
AUDIT_FIELDS = ("candidate_id", "delivered_rank")


def _audit_info(candidate: dict) -> dict:
    """候选的审计信息：只保留 id/排名，不把原始 candidate 塞进输出行。"""
    return {"candidate_id": candidate.get("id"),
            "delivered_rank": candidate.get("delivered_rank")}


def pairs_from_bundle(bundle: dict, limit: int, mode: str = "top-bottom") -> list[dict]:
    """从 bundle 抽 top/bottom（或相邻）交付候选对；候选材料全部过 safe_person。"""
    pairs = []
    for run in bundle.get("runs", []) or []:
        delivered = [candidate for candidate in (run.get("candidates") or [])
                     if isinstance(candidate, dict) and candidate.get("delivered")]
        if len(delivered) < 2:
            continue
        ordered = sorted(delivered, key=lambda candidate: (candidate.get("delivered_rank") is None,
                                                          candidate.get("delivered_rank") or 9999,
                                                          candidate.get("id") or 0))
        if mode == "adjacent":
            pairs_raw = [(ordered[index], ordered[index + 1]) for index in range(len(ordered) - 1)]
        else:
            pairs_raw = [(ordered[0], ordered[-1])]
        for top, bottom in pairs_raw:
            if top.get("id") == bottom.get("id"):
                continue
            pairs.append({
                "pair_id": f"R{len(pairs) + 1:02d}",
                "applicant": safe_person(run.get("applicant") or {}),
                "top": safe_person(top),
                "bottom": safe_person(bottom),
                "rank_a": _audit_info(top),
                "rank_b": _audit_info(bottom),
            })
            if len(pairs) >= limit:
                return pairs
    return pairs


def build_payloads(pairs: list[dict]) -> tuple[list[dict], list[dict]]:
    """构造 forward/backward judge 材料；A/B 位置交换不携带任何角色标签。"""
    forward = [{"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                "A": pair["top"], "B": pair["bottom"]} for pair in pairs]
    backward = [{"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                 "A": pair["bottom"], "B": pair["top"]} for pair in pairs]
    for payload in (forward, backward):
        assert_safe_material(payload)
    return forward, backward


def make_rows(pairs: list[dict], forward: dict, backward: dict) -> list[dict]:
    """把双向 verdict 归一成 A=top/B=bottom，并附审计 rank 字段。"""
    rows = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        verdict_forward = forward.get(pair_id, "tie")
        verdict_backward = backward.get(pair_id, "tie")
        # backward 中 A=bottom/B=top，归一成 A=top/B=bottom
        backward_as_forward = {"A": "B", "B": "A"}.get(verdict_backward, "tie")
        rows.append({
            "pair_id": pair_id,
            "forward": verdict_forward,
            "backward": backward_as_forward,
            "top_win": verdict_forward == "A",
            "bottom_win": verdict_forward == "B",
            "rank_a": dict(pair.get("rank_a") or {}),
            "rank_b": dict(pair.get("rank_b") or {}),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    top = sum(1 for row in rows if row["forward"] == "A") + 0.5 * sum(1 for row in rows if row["forward"] == "tie")
    consistent = sum(1 for row in rows if row["forward"] == row["backward"])
    consistency = round(consistent / n, 4) if n else 0.0
    return {"n": n,
            "top_win_rate": round(top / n, 4) if n else 0.0,
            "position_consistency": consistency,
            "ci95": {"top_win_rate": wilson_ci(top, n),
                     "position_consistency": wilson_ci(consistent, n)},
            "usable": consistency >= 0.8 if n else False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="交付名单内部成对评审（代理）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--mode", choices=("top-bottom", "adjacent"), default="top-bottom")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    if not all(env.get(k) for k in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    pairs = pairs_from_bundle(bundle, args.limit, args.mode)
    if not pairs:
        raise SystemExit("bundle 中没有可成对的交付候选（每个 run 至少 2 名 delivered）")
    forward_payload, backward_payload = build_payloads(pairs)
    forward, backward = [], []
    for start in range(0, len(forward_payload), 4):
        forward.extend(call(env, forward_payload[start:start + 4]))
    for start in range(0, len(backward_payload), 4):
        backward.extend(call(env, backward_payload[start:start + 4]))
    fmap = {row["pair_id"]: row.get("winner") for row in forward}
    bmap = {row["pair_id"]: row.get("winner") for row in backward}
    rows = make_rows(pairs, fmap, bmap)
    summary = summarize(rows)
    result = {
        "summary": summary,
        "n": summary["n"],
        "meta": {"bundle": bundle.get("meta") or {}, "mode": args.mode,
                 "limit": args.limit, "pairs": len(pairs)},
        "ci95": summary["ci95"],
        "judge_model": env.get("EVAL_JUDGE_MODEL"),
        "judge_provider": env.get("EVAL_JUDGE_PROVIDER") or env.get("EVAL_PROVIDER"),
        "rows": rows,
        "note": "交付名单内成对代理评审，不是人工真值；prompt 不含系统排序/审核字段。",
    }
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    win_ci = summary["ci95"]["top_win_rate"]
    consistency_ci = summary["ci95"]["position_consistency"]
    lines = ["# 交付名单内部成对评审（代理）", "",
             f"- 样本：{summary['n']} 对（{args.mode}）；"
             f"**top 胜率 {summary['top_win_rate']:.2%}**"
             f"（95% CI {win_ci['lo']:.2%}–{win_ci['hi']:.2%}）；"
             f"position consistency **{summary['position_consistency']:.2f}**"
             f"（95% CI {consistency_ci['lo']:.2f}–{consistency_ci['hi']:.2f}）；"
             f"usable **{summary['usable']}**",
             f"- judge：{result['judge_model']}；样本量 {summary['n']} 对，CI 为 Wilson 95%",
             "", "| pair | forward | backward(归一) | top win | rank_a | rank_b |",
             "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['pair_id']} | {row['forward']} | {row['backward']} | {row['top_win']} "
                     f"| {row['rank_a'].get('delivered_rank')} | {row['rank_b'].get('delivered_rank')} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
