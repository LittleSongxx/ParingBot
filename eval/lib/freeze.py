#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结集与供给池指纹工具（纯标准库，不连数据库）。

MANIFEST 记录两层指纹，任何一层变化都必须走“升版本 + 人工审阅”流程：

* ``base_sql_sha256``：eval profile 实际加载的全部 ``deploy/mysql/sql/base/*.sql``
  文件字节指纹（按文件名排序拼接，避免只改非种子 SQL 时漏检）；
* ``pool_digest``：从 base SQL 解析出的成员/偏好最终状态指纹（成员 id、档案关键
  字段、偏好字段全部纳入），用于证明“候选池本身没有被改写”；
* ``supply_additions``：eval profile 专属 SQL 目录里的供给写语句数量，必须为 0。

``find_supply_writes`` / ``find_scenario_references`` 供 check_freeze 与
build_frozen_labels / build_v4_scenarios 共用，保证“冻结”口径只有一份实现。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

BASE_SQL_DIR = Path("deploy/mysql/sql/base")
EVAL_SQL_DIR = Path("deploy/mysql/sql/eval")
SEED_SQL_NAME = "01-paringbot.sql"

# 语句必须以写操作开头（避免提示词文本里出现表名导致误报）
SUPPLY_WRITE_RE = re.compile(
    r"^\s*(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"`?(?:member_profile|roommate_preference)`?",
    re.IGNORECASE,
)

# 评测账号只允许出现在评测 SQL / 场景文件里；base 种子 SQL 出现即视为
# “按场景定制供给”的信号（历史 18/19 号 SQL 就是这种形态）。
SCENARIO_ACCOUNT_RE = re.compile(r"TEST_SCENARIO_[A-Za-z0-9_]+")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def base_sql_files(repo_root: Path | str) -> list[Path]:
    """按文件名排序返回 eval profile 会加载的 base SQL 文件清单。"""
    directory = Path(repo_root) / BASE_SQL_DIR
    return sorted(directory.glob("*.sql"))


def base_sql_sha256(repo_root: Path | str) -> str | None:
    """全部 base SQL 文件 + 文件名的稳定字节指纹；目录为空返回 None。"""
    files = base_sql_files(repo_root)
    if not files:
        return None
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _member_payload(member) -> dict:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "nickname": member.nickname,
        "gender": member.gender,
        "birth_date": _iso(member.birth_date),
        "rent_budget": member.rent_budget,
        "tidiness": member.tidiness,
        "occupation": member.occupation,
        "lease_term": member.lease_term,
        "store_id": member.store_id,
        "schedule_type": member.schedule_type,
        "has_pet": member.has_pet,
        "smoking": member.smoking,
        "self_intro": member.self_intro,
        "roommate_expectation": member.roommate_expectation,
        "interest_tags": list(member.interest_tags or []),
        "audit_status": member.audit_status,
        "enabled": member.enabled,
    }


def _preference_payload(preference) -> dict:
    return {
        "member_id": preference.member_id,
        "age_min": preference.age_min,
        "age_max": preference.age_max,
        "age_required": preference.age_required,
        "budget_min": preference.budget_min,
        "budget_max": preference.budget_max,
        "budget_required": preference.budget_required,
        "tidiness_min": preference.tidiness_min,
        "tidiness_required": preference.tidiness_required,
        "store_scope": preference.store_scope,
        "store_required": preference.store_required,
        "schedule_accept": list(preference.schedule_accept or []),
        "schedule_required": preference.schedule_required,
        "lease_min": preference.lease_min,
        "lease_required": preference.lease_required,
        "pet_accept": preference.pet_accept,
        "pet_required": preference.pet_required,
    }


def pool_digest(seed_data) -> str:
    """成员 + 偏好最终状态的 canonical JSON 指纹（与数据库/模型无关）。"""
    members = sorted(seed_data.members, key=lambda item: item.id)
    payload = {
        "members": [_member_payload(item) for item in members],
        "preferences": [
            _preference_payload(seed_data.preferences[item.id])
            for item in members if item.id in seed_data.preferences
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(text.encode("utf-8"))


def _strip_sql_comments(text: str) -> str:
    """去掉 -- / # 行注释与 /* */ 块注释，避免注释里的关键词造成误报。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--") or stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_statements(text: str) -> list[str]:
    """把 SQL 文本按 ; 拆成语句，跳过单/双引号字符串内部的分号。"""
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            buffer.append(char)
            if char == "\\" and index + 1 < len(text):
                buffer.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            buffer.append(char)
            index += 1
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _sql_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.rglob("*.sql"))
    return [path] if path.is_file() else []


def find_supply_writes(path: Path | str, *, allow_seed_inserts: bool = False) -> list[str]:
    """扫描文件/目录中的供给写语句，返回可读违规清单（空 = 干净）。"""
    violations: list[str] = []
    for sql_file in _sql_files(Path(path)):
        body = _strip_sql_comments(sql_file.read_text(encoding="utf-8", errors="replace"))
        for statement in split_statements(body):
            detail = " ".join(statement.split())[:140]
            head = statement.lstrip().upper()
            if SUPPLY_WRITE_RE.match(statement):
                if allow_seed_inserts and head.startswith("INSERT INTO"):
                    continue
                violations.append(f"{sql_file}: {detail}")
    return violations


def find_scenario_references(path: Path | str) -> list[str]:
    """扫描 SQL 中是否引用评测账号（base 种子 SQL 出现即视为定向供给）。"""
    findings: list[str] = []
    for sql_file in _sql_files(Path(path)):
        text = _strip_sql_comments(sql_file.read_text(encoding="utf-8", errors="replace"))
        for match in SCENARIO_ACCOUNT_RE.finditer(text):
            findings.append(f"{sql_file}: {match.group(0)}")
    return findings


def scan_eval_sql(eval_dir: Path | str | None = None, repo_root: Path | str | None = None) -> list[str]:
    """eval profile 专属 SQL 目录必须存在且不得有供给写语句。"""
    directory = Path(eval_dir) if eval_dir is not None else (
        Path(repo_root) / EVAL_SQL_DIR if repo_root is not None else None)
    if directory is None:
        return ["未指定 eval SQL 目录"]
    if not directory.is_dir():
        return [f"eval SQL 目录不存在：{directory}"]
    return find_supply_writes(directory)