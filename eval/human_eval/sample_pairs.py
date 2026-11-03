#!/usr/bin/env python3
"""从 quality-bundle 抽样人工盲评对，输出 CSV（不含系统结论）。"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--delivered", type=int, default=60)
    parser.add_argument("--rejected", type=int, default=20)
    args = parser.parse_args(argv)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    rows = []
    for run in bundle.get("runs", []):
        app = run.get("applicant") or {}
        for candidate in run.get("candidates", []):
            rows.append({"scenario": (run.get("run") or {}).get("run_no"),
                         "applicant": app.get("nickname"),
                         "candidate": candidate.get("nickname"),
                         "delivered": bool(candidate.get("delivered")),
                         "reject_code": candidate.get("reject_code")})
    delivered = [row for row in rows if row["delivered"]][:args.delivered]
    rejected = [row for row in rows if not row["delivered"]][:args.rejected]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pair_id", "scenario", "candidate", "delivered",
                                                    "annotator_a", "annotator_b", "note"])
        writer.writeheader()
        for index, row in enumerate(delivered + rejected, 1):
            writer.writerow({"pair_id": f"pair-{index:03d}", "scenario": row["scenario"],
                             "candidate": row["candidate"], "delivered": row["delivered"]})
    print(f"wrote {len(delivered) + len(rejected)} pairs -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
