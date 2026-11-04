#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 场景冻结守卫（P1）。

v4 标签尚未完成，因此只校验场景文件：
- MANIFEST 里的 sha256 与 scenarios.json 一致；
- 40 正向 + 8 负向；容量层 16/12/12；无重复格子；
- 负向 blocker 为 moment/intro。

用法：python eval/check_v4_freeze.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BASE = EVAL_DIR / "frozen" / "v4"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(base: Path = BASE) -> list[str]:
    errors: list[str] = []
    manifest_path = base / "MANIFEST.json"
    scenarios_path = base / "scenarios.json"
    if not manifest_path.is_file() or not scenarios_path.is_file():
        return [f"缺少 v4 冻结文件：{manifest_path} / {scenarios_path}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    declared = (manifest.get("scenarios") or {}).get("sha256")
    if declared != sha256(scenarios_path):
        errors.append("v4 scenarios.json 与 MANIFEST sha256 不一致")
    positives = [item for item in data.get("scenarios", []) if item.get("run")]
    negatives = [item for item in data.get("scenarios", []) if not item.get("run")]
    if len(positives) != 40:
        errors.append(f"v4 正向场景数 {len(positives)} != 40")
    if len(negatives) != 8:
        errors.append(f"v4 负向场景数 {len(negatives)} != 8")
    tiers: dict[str, int] = {}
    cells = set()
    for item in positives:
        tier = (item.get("ex_ante_capacity") or {}).get("tier")
        tiers[tier] = tiers.get(tier, 0) + 1
        cell = (item.get("profile", {}).get("store_id"),
                item.get("profile", {}).get("gender"),
                item.get("profile", {}).get("lease_term"))
        if cell in cells:
            errors.append(f"重复格子：{item.get('key')} {cell}")
        cells.add(cell)
        if (item.get("ex_ante_capacity") or {}).get("eligible", 0) < 1:
            errors.append(f"{item.get('key')} 容量为 0")
    if tiers != {"high": 16, "medium": 12, "low": 12}:
        errors.append(f"容量层不匹配：{tiers}")
    blockers = sorted({(item.get("expect") or {}).get("blocker") for item in negatives})
    if blockers != ["intro", "moment"]:
        errors.append(f"负向 blocker 不匹配：{blockers}")
    if (manifest.get("labels") or {}).get("status") != "pending":
        errors.append("v4 MANIFEST.labels.status 应为 pending")
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print("[FAIL]", error)
        return 1
    print("[OK] v4 scenarios.json 哈希/40+8/分层/负向类型一致；labels=pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
