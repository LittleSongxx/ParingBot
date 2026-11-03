"""读取 .env.eval 这类 KEY=VALUE 文件。"""
from __future__ import annotations

from pathlib import Path


def load_env(path: Path) -> dict:
    values = {}
    if not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
