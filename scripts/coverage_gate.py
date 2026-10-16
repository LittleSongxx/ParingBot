#!/usr/bin/env python3
"""覆盖率棘轮门禁：把各模块 jacoco CSV 汇总成总行覆盖率，与 baseline 文件比较。

- 低于 baseline - tolerance 判失败（默认 1pp）——防止"顺手删掉一片测试"或大段无测试代码无声上线。
- 覆盖率**上升**时提示更新 baseline（棘轮只上不下）。
- 日志里明说这是"汇总口径"，不替代按模块的 review：单模块波动请人工判断。

用法：
    python3 scripts/coverage_gate.py                # 检查（CI 用）
    python3 scripts/coverage_gate.py --update       # 把当前值写回 baseline（人工确认后）
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / "backend/jacoco-baseline.txt"
TOLERANCE = 0.01  # 允许 1pp 的抖动（重构搬代码等）


def collect() -> tuple[int, int, list[tuple[str, float, int, int]]]:
    rows = []
    covered = missed = 0
    for csv_path in sorted(ROOT.glob("backend/*/target/site/jacoco/jacoco.csv")) + \
            sorted(ROOT.glob("backend/*/*/target/site/jacoco/jacoco.csv")):
        module = csv_path.relative_to(ROOT / "backend").parts[0]
        with csv_path.open() as handle:
            entries = list(csv.DictReader(handle))
        line_covered = sum(int(entry["LINE_COVERED"]) for entry in entries)
        line_missed = sum(int(entry["LINE_MISSED"]) for entry in entries)
        if line_covered + line_missed == 0:
            continue
        rows.append((module, line_covered / (line_covered + line_missed), line_covered, line_missed))
        covered += line_covered
        missed += line_missed
    # 同一模块可能出现两个 csv（多模块工程里 app/api 分目录），按模块名去重保序
    merged: dict[str, tuple[float, int, int]] = {}
    for module, ratio, cov, mis in rows:
        if module not in merged:
            merged[module] = (ratio, cov, mis)
    return covered, missed, [(m, *v) for m, v in merged.items()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="把当前覆盖率写回 baseline")
    args = parser.parse_args()

    covered, missed, rows = collect()
    if not rows:
        print("coverage_gate: 未找到 jacoco CSV，请先运行 `mvn -Pintegration verify`", file=sys.stderr)
        return 2
    total = covered + missed
    ratio = covered / total
    for module, module_ratio, module_cov, module_mis in rows:
        print(f"  {module:24s} 行覆盖 {module_ratio * 100:5.1f}%  ({module_cov}/{module_cov + module_mis})")
    print(f"  汇总（{len(rows)} 模块）        行覆盖 {ratio * 100:5.1f}%  ({covered}/{total})")

    baseline = float(BASELINE_FILE.read_text().strip()) if BASELINE_FILE.exists() else None
    if args.update or baseline is None:
        BASELINE_FILE.write_text(f"{ratio:.4f}\n")
        print(f"coverage_gate: baseline 已写入 {BASELINE_FILE.relative_to(ROOT)} = {ratio:.4f}")
        return 0
    if ratio < baseline - TOLERANCE:
        print(f"coverage_gate: 失败——行覆盖率 {ratio * 100:.1f}% 低于基线 "
              f"{baseline * 100:.1f}%（容差 {TOLERANCE * 100:.0f}pp）", file=sys.stderr)
        return 1
    if ratio > baseline + TOLERANCE:
        print(f"coverage_gate: 通过，且较基线提升（{baseline * 100:.1f}% → {ratio * 100:.1f}%）；"
              f"确认后可用 --update 抬升基线")
        return 0
    print(f"coverage_gate: 通过（基线 {baseline * 100:.1f}%，容差 {TOLERANCE * 100:.0f}pp）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
