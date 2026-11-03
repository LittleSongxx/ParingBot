#!/usr/bin/env python3
"""计算双人评分的 Cohen's kappa 与简单一致率。"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def kappa(pairs):
    if not pairs:
        return 0.0, 0.0
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    expected = 0.0
    for label in labels:
        pa = sum(1 for a, _ in pairs if a == label) / n
        pb = sum(1 for _, b in pairs if b == label) / n
        expected += pa * pb
    return (observed - expected) / (1 - expected) if expected < 1 else 0.0, observed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    args = parser.parse_args(argv)
    pairs = []
    with args.labels.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("annotator_a") and row.get("annotator_b"):
                pairs.append((float(row["annotator_a"]), float(row["annotator_b"])))
    value, observed = kappa(pairs)
    print(f"n={len(pairs)} agreement={observed:.3f} kappa={value:.3f}")
    return 0 if value >= 0.6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
