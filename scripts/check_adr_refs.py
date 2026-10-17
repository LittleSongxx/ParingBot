#!/usr/bin/env python3
"""检查仓库里的 ADR 引用是否还能解析。

规则：
- `ADR-0001`..`ADR-0010` 必须对应 `docs/adr/000x-*.md`；
- 旧编号（0001-0023）必须出现在 `docs/adr/legacy-map.md` 的映射表里；
- 旧编号不允许再出现在 Java 后端代码或根 README（避免继续指向已删除的旧 ADR）；
- `docs/改动记录/` 与 `assistant/` 中的旧编号按历史/legacy 处理，只提示不失败。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"
LEGACY = ADR_DIR / "legacy-map.md"
SKIP_DIRS = {
    ".git", ".zcode", "node_modules", "target", "build", "dist", ".venv", "__pycache__",
    "run", "logs", "output", "artifacts", "data", ".idea", ".vscode",
}
TEXT_SUFFIXES = {
    ".java", ".kt", ".py", ".js", ".ts", ".vue", ".md", ".yml", ".yaml",
    ".xml", ".sql", ".sh", ".json", ".properties", ".txt",
}
REF = re.compile(r"ADR[-\s]?(\d{4})", re.IGNORECASE)


def new_adr_ids() -> set[str]:
    return {p.name[:4] for p in ADR_DIR.glob("0*.md") if p.name[:4].isdigit()}


def legacy_ids() -> set[str]:
    if not LEGACY.exists():
        return set()
    text = LEGACY.read_text(encoding="utf-8", errors="ignore")
    return set(REF.findall(text))


def iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > 1_500_000:
            continue
        yield path


def main() -> int:
    new_ids = new_adr_ids()
    old_ids = legacy_ids()
    failures: list[str] = []
    legacy_hits: list[str] = []
    ok = 0
    for path in iter_files():
        rel = path.relative_to(ROOT)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            for raw in REF.findall(line):
                ref = f"ADR-{raw}"
                if raw in new_ids:
                    ok += 1
                    continue
                if raw in old_ids:
                    # 旧编号只允许存在于历史记录/ADR 目录/assistant。
                    allowed = (
                        str(rel).startswith("docs/改动记录/")
                        or str(rel).startswith("docs/adr/")
                        or str(rel).startswith("assistant/")
                        # 原始验证输出是历史证据，不按现行文档重写。
                        or str(rel).startswith("eval/verification/")
                        # Flyway 迁移已应用后不可改写注释（会改变 checksum）。
                        or "/db/migration/" in str(rel)
                    )
                    if allowed:
                        legacy_hits.append(f"{rel}:{lineno}: {ref} (legacy)")
                    else:
                        failures.append(f"{rel}:{lineno}: {ref} 是旧编号，请改到新 ADR 或删除历史叙述")
                    continue
                failures.append(f"{rel}:{lineno}: {ref} 无法解析（既不是新 ADR，也不在 legacy-map）")

    print(f"new ADR ids: {', '.join(sorted(new_ids))}")
    print(f"resolved refs: {ok}; legacy refs: {len(legacy_hits)}; failures: {len(failures)}")
    for item in failures[:80]:
        print("FAIL " + item)
    if len(failures) > 80:
        print(f"... {len(failures) - 80} more failures")
    for item in legacy_hits[:20]:
        print("LEGACY " + item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
