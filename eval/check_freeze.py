#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结守卫：v3 场景/标签不许漂移，eval 供给池不许被改写。

fail-closed 检查四件事：
1. MANIFEST 里 scenarios.json / labels.json 的 sha256 与文件实际一致；
2. eval profile 真正加载的 ``deploy/mysql/sql/base/*.sql`` 指纹与 MANIFEST 一致；
3. 种子候选池的 canonical ``pool_digest`` 与 MANIFEST 一致（防止改 base 换供给）；
4. eval 专属 SQL 目录存在且没有任何 member_profile / roommate_preference 写语句；
   base 种子 SQL 中不得引用 TEST_SCENARIO_* 评测账号（防按场景定制供给）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import freeze as freeze_lib  # noqa: E402
from lib import seed as seedmod  # noqa: E402

FROZEN_DIR = ROOT / "frozen" / "v3"
EVAL_SQL_DIR = REPO / "deploy" / "mysql" / "sql" / "eval"
BASE_SQL_DIR = REPO / "deploy" / "mysql" / "sql" / "base"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _display(path: Path) -> str:
    try:
        return str(Path(path).relative_to(REPO))
    except ValueError:
        return str(path)


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_manifest(base: Path = FROZEN_DIR, repo_root: Path | str = REPO) -> list[str]:
    """校验冻结文件哈希、供给池指纹与标签/场景数量一致性；空列表 = 通过。"""
    base = Path(base)
    repo = Path(repo_root)
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

    # 供给池指纹：base SQL 全量字节 + 解析出的成员/偏好最终状态
    pool = manifest.get("pool") or {}
    declared_base = pool.get("base_sql_sha256")
    actual_base = freeze_lib.base_sql_sha256(repo)
    if not declared_base:
        errors.append("MANIFEST.pool 缺少 base_sql_sha256（无法证明 eval 数据未被改写）")
    elif actual_base and declared_base != actual_base:
        errors.append(f"base SQL 指纹不一致：MANIFEST {declared_base[:12]}… != 当前 {actual_base[:12]}…")
    declared_digest = pool.get("pool_digest")
    if not declared_digest:
        errors.append("MANIFEST.pool 缺少 pool_digest")
    else:
        try:
            seed_data = seedmod.load_seed(repo)
        except (OSError, ValueError) as exc:
            errors.append(f"无法从 base SQL 重算候选池：{exc}")
        else:
            actual_digest = freeze_lib.pool_digest(seed_data)
            if declared_digest != actual_digest:
                errors.append(f"候选池指纹不一致：MANIFEST {declared_digest[:12]}… != 当前 {actual_digest[:12]}…")

    computed_supply = len(scan_eval_sql(Path(repo) / "deploy" / "mysql" / "sql" / "eval"))
    declared_supply = manifest.get("supply_additions")
    if declared_supply not in (0, None):
        errors.append(f"MANIFEST.supply_additions 必须是 0，实际 {declared_supply}")
    elif computed_supply:
        errors.append(f"eval profile SQL 目录存在 {computed_supply} 条供给写语句")

    positives = {item.get("key") for item in scenarios.get("scenarios", []) if item.get("run")}
    labels_keys = {item.get("key") for item in labels.get("labels", [])}
    missing = positives - labels_keys
    extra = labels_keys - positives
    if missing:
        errors.append(f"正向场景缺少冻结标签：{sorted(missing)}")
    if extra:
        errors.append(f"标签里有场景集不存在的场景：{sorted(extra)}")
    if manifest.get("seed") != scenarios.get("seed"):
        errors.append("MANIFEST.seed 与 scenarios.seed 不一致")
    if manifest.get("protocol_version") != scenarios.get("protocol_version"):
        errors.append("MANIFEST.protocol_version 与 scenarios 不一致")
    return errors


def _display_violation(item: str) -> str:
    """把违规的绝对 SQL 路径转成仓库相对路径，同时保留语句摘要。"""
    path_text, separator, detail = item.partition(": ")
    if not separator:
        return item
    return f"{_display(Path(path_text))}: {detail}"


def scan_eval_sql(sql_dir: Path | str | None = None) -> list[str]:
    """eval profile 专属 SQL 目录：必须存在，且不得写 member_profile/roommate_preference。"""
    directory = Path(sql_dir) if sql_dir is not None else EVAL_SQL_DIR
    if not directory.is_dir():
        return [f"eval SQL 目录不存在：{_display(directory)}"]
    return [_display_violation(item) for item in freeze_lib.find_supply_writes(directory)]


def scan_repo_supply(repo_root: Path | str = REPO) -> list[str]:
    """整个 eval profile 的供给守卫（eval SQL + base SQL 里的评测账号引用）。"""
    repo = Path(repo_root)
    errors = scan_eval_sql(repo / "deploy" / "mysql" / "sql" / "eval")
    references = freeze_lib.find_scenario_references(repo / "deploy" / "mysql" / "sql" / "base")
    if references:
        errors.append("base 种子 SQL 出现评测账号引用（疑似按场景定制供给）："
                      + "; ".join(references[:5]))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冻结文件与 eval 供给守卫")
    parser.add_argument("--print", dest="verbose", action="store_true")
    parser.add_argument("--frozen-dir", type=Path, default=None)
    parser.add_argument("--sql-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    base = args.frozen_dir or FROZEN_DIR
    errors = check_manifest(base)
    errors.extend(scan_eval_sql(args.sql_dir) if args.sql_dir else scan_repo_supply())
    if args.verbose:
        manifest_path = Path(base) / "MANIFEST.json"
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
            print(f"[info] scenarios sha256: {(manifest.get('scenarios') or {}).get('sha256')}")
            print(f"[info] labels    sha256: {(manifest.get('labels') or {}).get('sha256')}")
            print(f"[info] pool digest: {(manifest.get('pool') or {}).get('pool_digest')}")
            print(f"[info] base sql : {(manifest.get('pool') or {}).get('base_sql_sha256')}")
            print(f"[info] protocol={manifest.get('protocol_version')} "
                  f"supply_additions={manifest.get('supply_additions')}")
    if errors:
        for item in errors:
            print(f"[FAIL] {item}")
        return 1
    print("[OK] 冻结文件哈希一致，base 供给池指纹一致，eval profile 无供给写语句")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())