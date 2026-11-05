#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付名单内部成对评审：排名最高的候选 vs 排名最低的候选，哪个更适合。

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

from pairwise_quality import call, load_env  # noqa: E402

RUBRIC = """你是独立盲评员。同一申请方有 A/B 两位候选，请判断谁更适合合租。
先分别核对硬条件（同性/双向必须项/租期档差）和生活习惯（作息/吸烟/宠物/整洁），再比较。
A/B 的位置不代表优劣，不要因为 A 在前就选 A；接近时选 tie。
只输出 JSON 数组，对象字段 pair_id, winner（A/B/tie）, reason（<=40字）。不要 markdown。
"""


def pairs_from_bundle(bundle: dict, limit: int) -> list[dict]:
    pairs = []
    for run in bundle.get("runs", []):
        delivered = [c for c in run.get("candidates", []) if c.get("delivered")]
        if len(delivered) < 2:
            continue
        ordered = sorted(delivered, key=lambda c: (c.get("delivered_rank") is None,
                                                   c.get("delivered_rank") or 9999))
        top, bottom = ordered[0], ordered[-1]
        if top.get("id") == bottom.get("id"):
            continue
        pairs.append({"pair_id": f"R{len(pairs)+1:02d}", "applicant": run.get("applicant") or {},
                      "top": top, "bottom": bottom})
        if len(pairs) >= limit:
            break
    return pairs


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    top = sum(1 for row in rows if row["forward"] == "A") + 0.5 * sum(1 for row in rows if row["forward"] == "tie")
    consistent = sum(1 for row in rows if row["forward"] == row["backward"])
    consistency = round(consistent / n, 4) if n else 0.0
    return {"n": n,
            "top_win_rate": round(top / n, 4) if n else 0.0,
            "position_consistency": consistency,
            "usable": consistency >= 0.8}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="交付名单内部成对评审（代理）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    if not all(env.get(k) for k in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    pairs = pairs_from_bundle(bundle, args.limit)
    forward_payload = []
    for pair in pairs:
        forward_payload.append({"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                                "A": pair["top"], "B": pair["bottom"]})
    backward_payload = []
    for pair in pairs:
        backward_payload.append({"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                                 "A": pair["bottom"], "B": pair["top"]})
    forward, backward = [], []
    for start in range(0, len(forward_payload), 4):
        forward.extend(call(env, forward_payload[start:start + 4]))
    for start in range(0, len(backward_payload), 4):
        backward.extend(call(env, backward_payload[start:start + 4]))
    fmap = {row["pair_id"]: row.get("winner") for row in forward}
    bmap = {row["pair_id"]: row.get("winner") for row in backward}
    rows = []
    for pair in pairs:
        pid = pair["pair_id"]
        f = fmap.get(pid, "tie")
        b = bmap.get(pid, "tie")
        # backward 中 A=bottom/B=top，归一成 A=top/B=bottom
        b_as_forward = {"A": "B", "B": "A"}.get(b, "tie")
        rows.append({"pair_id": pid, "forward": f, "backward": b_as_forward,
                     "top_win": f == "A", "bottom_win": f == "B"})
    summary = summarize(rows)
    result = {"summary": summary, "rows": rows, "note": "交付名单内成对代理评审，不是人工真值。"}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 交付名单内部成对评审（代理）", "",
             f"- 样本：{summary['n']} 对（每 run 的 rank 最高 vs 最低）；"
             f"**top 胜率 {summary['top_win_rate']:.2%}**；"
             f"position consistency **{summary['position_consistency']:.2f}**；usable **{summary['usable']}**",
             "", "| pair | forward | backward(归一) | top win |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['pair_id']} | {row['forward']} | {row['backward']} | {row['top_win']} |")
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
