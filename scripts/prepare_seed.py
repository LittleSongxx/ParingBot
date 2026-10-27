# -*- coding: utf-8 -*-
"""把旧 AIColiving 的 MySQL 导出迁移为 SmartLect 种子库。

做的事只有两件，其余数据一条不改：
1. 头部注释里的库名 ai_coliving -> smartlect；
2. user 表所有密码替换为 PBKDF2-SHA256 哈希（与 backend/common/security.py 同格式）。

这是本机一次性的迁移工具：源文件是旧工程的 ai_coliving.sql，不在本仓库内。
新环境只需要直接导入生成的 deploy/mysql/init/01-smartlect.sql。
"""
import hashlib
import os
import re
import sys
from pathlib import Path

ITERATIONS = 120000
SOURCE = Path("/home/song/code/Agent/multi-agent/AIColiving/ai_coliving.sql")
TARGET = Path(__file__).resolve().parents[1] / "deploy/mysql/init/01-smartlect.sql"


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def main() -> int:
    if not SOURCE.exists():
        print(f"[skip] source not found: {SOURCE}")
        return 1
    sql = SOURCE.read_text(encoding="utf-8")
    hashed = {"admin": hash_password("admin"), "123456": hash_password("123456")}

    # 只替换第 3 列（password）。不能对整行做「替换第一个 'admin'」：
    # admin 这一行 username 和 password 都是 admin，按整行替换会改错列。
    pattern = re.compile(
        r"(INSERT INTO `user` VALUES \(\d+, '[^']*', ')([^']*)(')", re.S)
    sql, count = pattern.subn(
        lambda m: m.group(1) + hashed.get(m.group(2), m.group(2)) + m.group(3), sql)
    sql = sql.replace("ai_coliving", "smartlect")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(sql, encoding="utf-8")
    print(f"[ok] users hashed: {count} rows; target: {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
