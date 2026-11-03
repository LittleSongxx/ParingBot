#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结守卫：v3 场景/标签不许漂移，eval 数据 profile 不许补供给。

CI 里在跑评测之前执行（fail-closed），它检查三件事：

1. MANIFEST 里记录的 scenarios.json / labels.json 的 sha256 与文件实际内容一致；
2. 标签数 = 正向场景数（防止有人只改标签不改场景、或漏算场景）；
3. deploy/mysql/sql/eval/ 下没有任何写 member_profile / roommate_preference 的
   SQL 语句 —— eval profile 只能有 base 数据，一旦出现供给补丁，评测就不再是
   「离线冻结」的。

用法：
  python3 eval/check_freeze.py           # 校验，失败返回 1
  python3 eval/check_freeze.py --print   # 额外打印哈希与扫描结果
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
FROZEN_DIR = EVAL_DIR / "frozen" / "v3"
EVAL_SQL_DIR = REPO / "deploy" / "mysql" / "sql" / "eval"

# 这些语句会改租客档案/合住偏好；eval profile 里出现即视为供给污染
WRITE_PATTERN = re.compile(
    r"\b(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE)\s+`?(member_profile|roommate_preference)`?",
    re.IGNORECASE,
)
# 表名在上述语句之外出现（例如 INSERT 多表写法）也按可疑处理
TABLE_PATTERN = re.compile(r"\b(member_profile|roommate_preference)\b", re.IGNORECASE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display(path: Path) -> str:
    """报告里优先显示相对仓库根目录的路径，临时目录场景回退到绝对路径。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_manifest(base: Path = FROZEN_DIR) -> list[str]:
    """校验冻结文件哈希与标签/场景数量一致性，返回错误清单（空表示通过）。"""
    errors: list[str] = []
    manifest_path = base / "MANIFEST.json"
    scenarios_path = base / "scenarios.json"
    labels_path = base / "labels.json"
    for path in (manifest_path, scenarios_path, labels_path):
        if not path.is_file():
            errors.append(f"缺少冻结文件：{path}")
    if errors:
        return errors
    manifest = _read_json(manifest_path)
    scenarios = _read_json(scenarios_path)
    labels = _read_json(labels_path)
    for name, path in (("scenarios", scenarios_path), ("labels", labels_path)):
        declared = (manifest.get(name) or {}).get("sha256")
        actual = _sha256(path)
        if not declared:
            errors.append(f"MANIFEST 缺少 {name}.sha256")
        elif declared != actual:
            errors.append(f"{path.name} 哈希不一致：文件 {actual} != MANIFEST {declared}")
    if manifest.get("supply_additions") not in (0, None):
        errors.append(f"MANIFEST.supply_additions 必须是 0，实际 {manifest.get('supply_additions')}")
    positive_keys = {item.get("key") for item in scenarios.get("scenarios", []) if item.get("run")}
    label_keys = {item.get("key") for item in labels.get("labels", [])}
    missing = positive_keys - label_keys
    extra = label_keys - positive_keys
    if missing:
        errors.append(f"正向场景缺少冻结标签：{sorted(missing)}")
    if extra:
        errors.append(f"标签里有场景集不存在的场景：{sorted(extra)}")
    if manifest.get("seed") != scenarios.get("seed"):
        errors.append("MANIFEST.seed 与 scenarios.seed 不一致")
    if manifest.get("protocol_version") != scenarios.get("protocol_version"):
        errors.append("MANIFEST.protocol_version 与 scenarios 不一致")
    return errors


def scan_eval_sql(sql_dir: Path = EVAL_SQL_DIR) -> list[str]:
    """扫描 eval profile 的 SQL 目录，返回出现供给写语句的文件清单。"""
    violations: list[str] = []
    if not sql_dir.is_dir():
        return violations
    for path in sorted(sql_dir.rglob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("--"):
                continue
            if WRITE_PATTERN.search(line):
                violations.append(f"{_display(path)}:{line_no} 写入了租客供给："
                                  f"{stripped[:120]}")
            elif TABLE_PATTERN.search(line) and re.search(
                    r"\b(INSERT|UPDATE|REPLACE|DELETE)\b", line, re.IGNORECASE):
                violations.append(f"{_display(path)}:{line_no} 疑似改动租客供给："
                                  f"{stripped[:120]}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v3 冻结文件与 eval 供给守卫")
    parser.add_argument("--print", dest="verbose", action="store_true", help="打印哈希与扫描详情")
    parser.add_argument("--frozen-dir", type=Path, default=None, help="冻结目录（测试用）")
    parser.add_argument("--sql-dir", type=Path, default=None, help="eval SQL 目录（测试用）")
    args = parser.parse_args(argv)
    base = args.frozen_dir or FROZEN_DIR
    sql_dir = args.sql_dir or EVAL_SQL_DIR
    errors = check_manifest(base)
    errors.extend(scan_eval_sql(sql_dir))
    if args.verbose:
        manifest_path = base / "MANIFEST.json"
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
            print(f"[info] scenarios sha256: {(manifest.get('scenarios') or {}).get('sha256')}")
            print(f"[info] labels    sha256: {(manifest.get('labels') or {}).get('sha256')}")
            print(f"[info] seed={manifest.get('seed')} protocol={manifest.get('protocol_version')} "
                  f"supply_additions={manifest.get('supply_additions')}")
            print(f"[info] pool: {json.dumps(manifest.get('pool'), ensure_ascii=False)}")
        print(f"[info] 扫描 eval SQL 目录：{sql_dir}"
              f"（{'存在' if sql_dir.is_dir() else '不存在'}）")
    if errors:
        for item in errors:
            print(f"[FAIL] {item}")
        return 1
    print("[OK] 冻结文件哈希一致，eval profile 无租客供给写语句")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())