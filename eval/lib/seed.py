#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 MySQL 初始化 SQL 里读离线种子数据（纯标准库，不连数据库）。

评测的候选池来自仓库自带的种子 SQL：
  deploy/mysql/sql/base/01-paringbot.sql      （新结构，W3 迁移后）
  deploy/mysql/init/01-paringbot.sql          （旧结构，兼容回退）

只解析 member_profile 与 roommate_preference 两张表的 INSERT 行，不执行 SQL、
不连数据库。解析出的 Member / Preference 是后续规则判定、场景生成、冻结标签的
唯一数据来源，所以这里不做任何业务推断，字段按 SQL 原值保留。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# 种子 SQL 的候选路径（新结构优先，旧结构回退）
SEED_SQL_CANDIDATES = (
    "deploy/mysql/sql/base/01-paringbot.sql",
    "deploy/mysql/init/01-paringbot.sql",
)

# 两张表的列顺序（与 01-paringbot.sql 的 CREATE TABLE 一致）
MEMBER_PROFILE_COLUMNS = (
    "id", "user_id", "nickname", "gender", "birth_date", "rent_budget", "tidiness",
    "occupation", "lease_term", "store_id", "schedule_type", "has_pet", "smoking",
    "self_intro", "roommate_expectation", "interest_tags", "photo_paths",
    "audit_status", "audit_remark", "audit_time", "enabled", "create_time", "update_time",
)
ROOMMATE_PREFERENCE_COLUMNS = (
    "id", "member_id", "age_min", "age_max", "age_required", "budget_min", "budget_max",
    "budget_required", "tidiness_min", "tidiness_required", "store_scope", "store_required",
    "schedule_accept", "schedule_required", "lease_min", "lease_required", "pet_accept",
    "pet_required", "create_time", "update_time",
)

APPROVED = "已通过"
ENABLED = "是"

_INSERT_PREFIX = "INSERT INTO `"
_ESCAPES = {
    "0": "\0", "'": "'", '"': '"', "b": "\b", "n": "\n", "r": "\r",
    "t": "\t", "Z": "\x1a", "\\": "\\", "%": "\\%", "_": "\\_",
}


@dataclass
class Member:
    """租客档案（member_profile 的一行）。"""

    id: int = 0
    user_id: int = 0
    nickname: str = ""
    gender: str = ""
    birth_date: date | None = None
    rent_budget: int | None = None
    tidiness: str = ""
    occupation: str = ""
    lease_term: str = ""
    store_id: int | None = None
    schedule_type: str = ""
    has_pet: str = ""
    smoking: str = ""
    self_intro: str = ""
    roommate_expectation: str = ""
    interest_tags: list[str] = field(default_factory=list)
    audit_status: str = ""
    enabled: str = ENABLED

    def age(self, as_of: date | None = None) -> int | None:
        """按出生日期现算年龄（委托 lib.rules.age_of 的同一口径）。"""
        if self.birth_date is None:
            return None
        today = as_of or date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day))


@dataclass
class Preference:
    """合住偏好（roommate_preference 的一行）。"""

    member_id: int = 0
    age_min: int | None = None
    age_max: int | None = None
    age_required: str = "加分"
    budget_min: int | None = None
    budget_max: int | None = None
    budget_required: str = "加分"
    tidiness_min: str | None = None
    tidiness_required: str = "加分"
    store_scope: str = "不限"
    store_required: str = "加分"
    schedule_accept: list[str] = field(default_factory=list)
    schedule_required: str = "加分"
    lease_min: str | None = None
    lease_required: str = "加分"
    pet_accept: str = "无所谓"
    pet_required: str = "加分"


@dataclass
class SeedData:
    """一份种子数据的解析结果。"""

    members: list[Member] = field(default_factory=list)
    preferences: dict[int, Preference] = field(default_factory=dict)
    source: str = ""

    def member(self, member_id: int) -> Member | None:
        for item in self.members:
            if item.id == member_id:
                return item
        return None


def _unescape(raw: str) -> str:
    """把 MySQL 字符串字面量里的转义还原成真实字符。"""
    out: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            nxt = raw[index + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _parse_values(text: str, start: int) -> tuple[list[list], int]:
    """从 start 位置开始解析 VALUES 后面的一个或多个元组，返回 (行列表, 结束位置)。"""
    rows: list[list] = []
    pos = start
    length = len(text)
    while pos < length:
        # 跳过空白与逗号，找到下一个元组起点
        while pos < length and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= length or text[pos] != "(":
            break
        pos += 1
        row: list = []
        while pos < length:
            while pos < length and text[pos] in " \t\r\n,":
                pos += 1
            if pos >= length or text[pos] == ")":
                break
            char = text[pos]
            if char == "'":
                pos += 1
                chunk: list[str] = []
                while pos < length:
                    if text[pos] == "\\" and pos + 1 < length:
                        chunk.append(text[pos:pos + 2])
                        pos += 2
                        continue
                    if text[pos] == "'":
                        if pos + 1 < length and text[pos + 1] == "'":
                            chunk.append("'")
                            pos += 2
                            continue
                        pos += 1
                        break
                    chunk.append(text[pos])
                    pos += 1
                row.append(_unescape("".join(chunk)))
                continue
            token_start = pos
            while pos < length and text[pos] not in ",)":
                pos += 1
            token = text[token_start:pos].strip()
            if token.upper() == "NULL":
                row.append(None)
            elif re.fullmatch(r"-?\d+", token):
                row.append(int(token))
            elif re.fullmatch(r"-?\d+\.\d+", token):
                row.append(float(token))
            else:
                row.append(token)
            while pos < length and text[pos] in " \t\r\n":
                pos += 1
            if pos < length and text[pos] == ",":
                pos += 1
                continue
            if pos < length and text[pos] == ")":
                break
        while pos < length and text[pos] in " \t\r\n":
            pos += 1
        if pos < length and text[pos] == ")":
            pos += 1
        rows.append(row)
        # 仅当后面还跟着逗号+左括号时才继续解析下一个元组
        look = pos
        while look < length and text[look] in " \t\r\n":
            look += 1
        if look < length and text[look] == ",":
            after = look + 1
            while after < length and text[after] in " \t\r\n":
                after += 1
            if after < length and text[after] == "(":
                pos = after
                continue
        break
    return rows, pos


def _iter_insert_rows(text: str, table: str):
    """按行扫描 INSERT 语句，产出目标表的每一行值（种子 SQL 为一行一条记录）。"""
    prefix = _INSERT_PREFIX + table + "` VALUES ("
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        start = line.index("VALUES") + len("VALUES")
        rows, _end = _parse_values(line, start)
        for row in rows:
            yield row


def _to_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _tags(value) -> list[str]:
    """把兴趣标签/作息等多值字段拆成清单，兼容 SQL 字符串与 JSON 数组两种来源。"""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    return [item.strip() for item in str(value).replace("，", ",").split(",") if item.strip()]


def _row_dict(columns: tuple, row: list) -> dict:
    if len(row) != len(columns):
        raise ValueError(f"列数不匹配：期望 {len(columns)} 列，实际 {len(row)} 列，行={row[:3]}")
    return dict(zip(columns, row))


def _member_from_row(row: list) -> Member:
    data = _row_dict(MEMBER_PROFILE_COLUMNS, row)
    return Member(
        id=int(data["id"]),
        user_id=int(data["user_id"] or 0),
        nickname=data["nickname"] or "",
        gender=data["gender"] or "",
        birth_date=_to_date(data["birth_date"]),
        rent_budget=None if data["rent_budget"] is None else int(data["rent_budget"]),
        tidiness=data["tidiness"] or "",
        occupation=data["occupation"] or "",
        lease_term=data["lease_term"] or "",
        store_id=None if data["store_id"] is None else int(data["store_id"]),
        schedule_type=data["schedule_type"] or "",
        has_pet=data["has_pet"] or "",
        smoking=data["smoking"] or "",
        self_intro=data["self_intro"] or "",
        roommate_expectation=data["roommate_expectation"] or "",
        interest_tags=_tags(data["interest_tags"]),
        audit_status=data["audit_status"] or "",
        enabled=data["enabled"] or ENABLED,
    )


def _preference_from_row(row: list) -> Preference:
    data = _row_dict(ROOMMATE_PREFERENCE_COLUMNS, row)
    return Preference(
        member_id=int(data["member_id"]),
        age_min=None if data["age_min"] is None else int(data["age_min"]),
        age_max=None if data["age_max"] is None else int(data["age_max"]),
        age_required=data["age_required"] or "加分",
        budget_min=None if data["budget_min"] is None else int(data["budget_min"]),
        budget_max=None if data["budget_max"] is None else int(data["budget_max"]),
        budget_required=data["budget_required"] or "加分",
        tidiness_min=data["tidiness_min"],
        tidiness_required=data["tidiness_required"] or "加分",
        store_scope=data["store_scope"] or "不限",
        store_required=data["store_required"] or "加分",
        schedule_accept=_tags(data["schedule_accept"]),
        schedule_required=data["schedule_required"] or "加分",
        lease_min=data["lease_min"],
        lease_required=data["lease_required"] or "加分",
        pet_accept=data["pet_accept"] or "无所谓",
        pet_required=data["pet_required"] or "加分",
    )


def member_from_payload(payload: dict, member_id: int = 0, user_id: int = 0) -> Member:
    """把 API 档案 payload（或场景 JSON 里的 profile 段）转成 Member。

    场景申请人是按协议生成的虚拟档案，没有数据库行；冻结标签用它现算硬规则与排序，
    所以这里只认 payload 字段，不做任何默认值推断。
    """
    data = payload or {}
    return Member(
        id=member_id,
        user_id=user_id,
        nickname=data.get("nickname") or "",
        gender=data.get("gender") or "",
        birth_date=_to_date(data.get("birth_date")),
        rent_budget=None if data.get("rent_budget") is None else int(data["rent_budget"]),
        tidiness=data.get("tidiness") or "",
        occupation=data.get("occupation") or "",
        lease_term=data.get("lease_term") or "",
        store_id=None if data.get("store_id") is None else int(data["store_id"]),
        schedule_type=data.get("schedule_type") or "",
        has_pet=data.get("has_pet") or "",
        smoking=data.get("smoking") or "",
        self_intro=data.get("self_intro") or "",
        roommate_expectation=data.get("roommate_expectation") or "",
        interest_tags=_tags(data.get("interest_tags")),
        audit_status=data.get("audit_status") or "",
        enabled=data.get("enabled") or ENABLED,
    )


def preference_from_payload(payload: dict, member_id: int = 0) -> Preference:
    """把 API 偏好 payload（或场景 JSON 里的 preference 段）转成 Preference。

    API 用「不限」表示不设下限，落库是空值；这里把两种写法都归一成 None。
    """
    data = payload or {}

    def _int(name):
        value = data.get(name)
        return None if value in (None, "", "不限") else int(value)

    def _choice(name, default):
        value = data.get(name)
        if value in (None, "", "不限"):
            return None if name in ("tidiness_min", "lease_min") else default
        return value

    schedule = data.get("schedule_accept")
    if isinstance(schedule, str):
        schedule = _tags(schedule)
    return Preference(
        member_id=member_id,
        age_min=_int("age_min"),
        age_max=_int("age_max"),
        age_required=data.get("age_required") or "加分",
        budget_min=_int("budget_min"),
        budget_max=_int("budget_max"),
        budget_required=data.get("budget_required") or "加分",
        tidiness_min=_choice("tidiness_min", None),
        tidiness_required=data.get("tidiness_required") or "加分",
        store_scope=data.get("store_scope") or "不限",
        store_required=data.get("store_required") or "加分",
        schedule_accept=list(schedule or []),
        schedule_required=data.get("schedule_required") or "加分",
        lease_min=_choice("lease_min", None),
        lease_required=data.get("lease_required") or "加分",
        pet_accept=data.get("pet_accept") or "无所谓",
        pet_required=data.get("pet_required") or "加分",
    )


def seed_sql_path(repo_root: Path | str) -> Path:
    """定位种子 SQL：新结构优先，旧结构回退；都不存在时报错。"""
    root = Path(repo_root)
    for relative in SEED_SQL_CANDIDATES:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    searched = "、".join(str(root / relative) for relative in SEED_SQL_CANDIDATES)
    raise FileNotFoundError(f"找不到种子 SQL，已尝试：{searched}")


def load_seed_from_sql(path: Path | str) -> SeedData:
    """解析指定的种子 SQL 文件。"""
    sql_path = Path(path)
    text = sql_path.read_text(encoding="utf-8", errors="replace")
    members = [_member_from_row(row) for row in _iter_insert_rows(text, "member_profile")]
    preferences = {}
    for row in _iter_insert_rows(text, "roommate_preference"):
        item = _preference_from_row(row)
        preferences[item.member_id] = item
    members.sort(key=lambda item: item.id)
    if not members:
        raise ValueError(f"种子 SQL 里没有解析到 member_profile 记录：{sql_path}")
    return SeedData(members=members, preferences=preferences, source=str(sql_path))


def load_seed(repo_root: Path | str) -> SeedData:
    """从仓库根目录加载种子数据（Member 列表 + 按会员 id 索引的偏好）。"""
    return load_seed_from_sql(seed_sql_path(repo_root))


def approved_candidates(seed: SeedData) -> list[Member]:
    """可进候选池的租客：审核已通过且启用中。"""
    return [item for item in seed.members
            if item.audit_status == APPROVED and item.enabled == ENABLED]


def seed_stats(seed: SeedData) -> dict:
    """种子数据的基本统计（写 MANIFEST、报告与单测断言用）。"""
    approved = approved_candidates(seed)
    by_gender: dict[str, int] = {}
    by_store: dict[str, int] = {}
    for item in approved:
        by_gender[item.gender] = by_gender.get(item.gender, 0) + 1
        by_store[str(item.store_id)] = by_store.get(str(item.store_id), 0) + 1
    return {
        "source": seed.source,
        "members": len(seed.members),
        "preferences": len(seed.preferences),
        "approved": len(approved),
        "approved_with_preference": len([item for item in approved
                                        if item.id in seed.preferences]),
        "approved_by_gender": dict(sorted(by_gender.items())),
        "approved_by_store": dict(sorted(by_store.items(), key=lambda pair: int(pair[0]))),
    }