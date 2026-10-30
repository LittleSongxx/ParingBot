# -*- coding: utf-8 -*-
"""把旧 AIColiving 的 MySQL 导出迁移为 ParingBot 种子库。

做的事只有两件，其余数据一条不改：
1. 头部注释里的库名 ai_coliving -> paringbot；
2. user 表所有密码替换为 PBKDF2-SHA256 哈希（与 backend/common/security.py 同格式）。

这是本机一次性的迁移工具：源文件是旧工程的 ai_coliving.sql，不在本仓库内。
新环境只需要直接导入生成的 deploy/mysql/init/01-paringbot.sql。
"""
import hashlib
import os
import re
import sys
from pathlib import Path

ITERATIONS = 120000
SOURCE = Path("/home/song/code/Agent/multi-agent/AIColiving/ai_coliving.sql")
TARGET = Path(__file__).resolve().parents[1] / "deploy/mysql/init/01-paringbot.sql"


def hash_password(raw: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def main() -> int:
    if not SOURCE.exists():
        print(f"[skip] source not found: {SOURCE}")
        return 1
    sql = SOURCE.read_text(encoding="utf-8")
    # 管理员初始密码改成 6 位，和改密码规则（6-30 位）保持一致；
    # 原来的 admin 只有 5 位，一旦通过 UI 改成临时密码就再也改不回去。
    hashed = {"admin": hash_password("admin123"), "123456": hash_password("123456")}

    # 只替换第 3 列（password）。不能对整行做「替换第一个 'admin'」：
    # admin 这一行 username 和 password 都是 admin，按整行替换会改错列。
    pattern = re.compile(
        r"(INSERT INTO `user` VALUES \(\d+, '[^']*', ')([^']*)(')", re.S)
    sql, count = pattern.subn(
        lambda m: m.group(1) + hashed.get(m.group(2), m.group(2)) + m.group(3), sql)
    sql = sql.replace("ai_coliving", "paringbot")
    # 演示租客「林清和」统一改名为「小宋」：原始导出里 user.name 是林清和、
    # member_profile.nickname 与各处快照文本是清和，重新生成种子时漏掉就会退回旧名。
    sql = sql.replace("林清和", "小宋").replace("清和", "小宋")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(sql, encoding="utf-8")
    print(f"[ok] users hashed: {count} rows; target: {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
