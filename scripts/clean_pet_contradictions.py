#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据清洗：消除 has_pet=无 与“养宠”兴趣/简介/动态/画像的矛盾。

背景（2026-11 质量根因）：
- 770 名 has_pet=无 的候选里，323 名的兴趣标签含“养猫/养狗/养鱼/爬宠/撸猫”等，
  177 名的自我介绍把养宠写成事实，35 条动态在讲“养狗/撸猫”；
- 审核官会把兴趣标签误读成真实养宠，判 PREFERENCE_CONFLICT（V4_30 的 8/8 假否决）；
- 内容画像/claim 也会因此生成与档案矛盾的内容。

本脚本直接改 `deploy/mysql/sql/base/01-paringbot.sql` 的 INSERT 行（评测的种子池解析
只读 INSERT，UPDATE 不会被 freeze_lib 计入 pool_digest；所以必须在源数据上改）：

1. has_pet=无 的成员：删除“养猫/养狗/养鱼/爬宠/撸猫/铲屎官…”等**所有权**标签；
   “宠物摄影/宠物公益”这类话题标签保留。
2. 自我介绍/画像小结/画像依据里的所有权句式改成“喜欢/云吸/看视频”等话题表达。
3. 动态里“养狗/撸猫/喂猫/铲屎”等改成“逛宠物公园/云吸猫/看视频/打扫卫生”。

幂等：重复执行不会再改；`--verify` 只读校验清洗后无残留。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SQL_PATH = REPO / "deploy" / "mysql" / "sql" / "base" / "01-paringbot.sql"

# 只清理“所有权”标签；宠物摄影/宠物公益/看宠物视频只是话题，保留。
OWNERSHIP_TAGS = (
    "养猫", "养狗", "养鸟", "养鱼", "养仓鼠", "养兔", "养乌龟", "养宠物", "爬宠",
    "撸猫", "撸狗", "铲屎官", "猫奴", "狗奴", "猫主子", "喂猫", "喂狗", "猫砂",
)
NEGATIVE_PREFIX = ("不", "无", "没", "别", "拒绝")

# 自我介绍 / 画像：保持“是在聊兴趣”而不是“我在养”
INTRO_REPLACEMENTS = (
    ("养宠物", "喜欢小动物"),
    ("养仓鼠", "看仓鼠视频"),
    ("养乌龟", "逛水族店"),
    ("养兔", "看兔子视频"),
    ("养猫", "云吸猫"),
    ("养狗", "云吸狗"),
    ("养鸟", "观鸟"),
    ("养鱼", "逛水族店"),
    ("撸猫", "云吸猫"),
    ("撸狗", "云吸狗"),
    ("铲屎官", "爱宠人士"),
    ("猫奴", "爱猫人士"),
    ("狗奴", "爱狗人士"),
    ("猫主子", "猫咪"),
    ("喂猫", "看猫视频"),
    ("喂狗", "看狗视频"),
    ("猫砂", "收纳"),
)

# 动态正文里多带“去/给/这周末”等动作，替换成话题表达才通顺
MOMENT_REPLACEMENTS = (
    ("养宠物", "看宠物视频"),
    ("养仓鼠", "看仓鼠视频"),
    ("养乌龟", "逛水族店"),
    ("养兔", "看兔子视频"),
    ("养猫", "逛猫咖"),
    ("养狗", "逛宠物公园"),
    ("养鸟", "去公园观鸟"),
    ("养鱼", "逛水族店"),
    ("撸猫", "云吸猫"),
    ("撸狗", "云吸狗"),
    ("铲屎官", "爱宠人士"),
    ("猫奴", "爱猫人士"),
    ("狗奴", "爱狗人士"),
    ("猫主子", "猫咪"),
    ("喂猫", "看猫视频"),
    ("喂狗", "看狗视频"),
    ("猫砂", "收纳"),
)

ANIMALS = "猫|狗|仓鼠|兔子|鹦鹉|鸟|鱼|乌龟|爬宠|宠物"
OWN_RE = re.compile(
    rf"(?:我|家里|家中|目前|现在)?(?:养了|养着|在养|养)\s*(?:一|两|三|几)?\s*(?:只|条|缸)?\s*({ANIMALS})")
HAVE_RE = re.compile(rf"(?:家里|家中|我)?有\s*(?:一|两|三|几)?\s*(?:只|条|缸)?\s*({ANIMALS})")
MY_RE = re.compile(rf"我的({ANIMALS})")
# “爬宠”本身会被替换成“看爬宠视频”，重复执行时不能再次替换，否则会叠成
# “看看爬宠视频视频”；用前后断言保证幂等。
CRAWL_RE = re.compile(r"(?<!看)爬宠(?!视频)")

MEMBER_COLUMNS = 23
MOMENT_MEMBER_INDEX = 1
MOMENT_CONTENT_INDEX = 2
PORTRAIT_MEMBER_INDEX = 1
PORTRAIT_TAG_INDEXES = (3, 4, 5)
PORTRAIT_TEXT_INDEXES = (6, 7)


def parse_values(line: str) -> tuple[str, list[tuple[str, str]]]:
    """解析一行 `INSERT INTO `table` VALUES (...);`。"""
    table = line.split("`")[1]
    marker = "VALUES ("
    start = line.index(marker) + len(marker)
    end = line.rstrip().rfind(");")
    body = line[start:end]
    values: list[tuple[str, str]] = []
    i = 0
    while i < len(body):
        while i < len(body) and body[i] == " ":
            i += 1
        if i >= len(body):
            break
        if body[i] == "'":
            i += 1
            buf: list[str] = []
            while i < len(body):
                ch = body[i]
                if ch == "\\" and i + 1 < len(body):
                    nxt = body[i + 1]
                    buf.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0",
                                "Z": "\x1a", "b": "\b"}.get(nxt, nxt))
                    i += 2
                elif ch == "'":
                    if i + 1 < len(body) and body[i + 1] == "'":
                        buf.append("'")
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    buf.append(ch)
                    i += 1
            values.append(("str", "".join(buf)))
        else:
            j = i
            while j < len(body) and body[j] != ",":
                j += 1
            values.append(("raw", body[i:j].strip()))
            i = j
        if i < len(body) and body[i] == ",":
            i += 1
    return table, values


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r"))


def dump_insert(table: str, values: list[tuple[str, str]]) -> str:
    parts = [f"'{escape(value)}'" if kind == "str" else value for kind, value in values]
    return f"INSERT INTO `{table}` VALUES ({', '.join(parts)});"


def _animal_phrase(animal: str, for_moment: bool) -> str:
    if animal == "宠物":
        return "看宠物视频" if for_moment else "喜欢小动物"
    return f"看{animal}视频" if for_moment else f"喜欢{animal}"


def clean_text(text: str, moment: bool = False) -> str:
    if not text:
        return text
    replacements = MOMENT_REPLACEMENTS if moment else INTRO_REPLACEMENTS
    for old, new in replacements:
        text = text.replace(old, new)

    def own(match: re.Match) -> str:
        return _animal_phrase(match.group(1), moment)

    text = OWN_RE.sub(own, text)
    text = HAVE_RE.sub(own, text)
    text = MY_RE.sub(lambda m: m.group(1), text)
    text = CRAWL_RE.sub("看爬宠视频", text)
    return text


def clean_tags(value: str) -> str:
    tags = [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]
    kept = [item for item in tags
            if item.startswith(NEGATIVE_PREFIX)
            or not any(word in item for word in OWNERSHIP_TAGS)]
    return ",".join(kept) if kept else "生活"


def clean_lines(lines: list[str]) -> tuple[list[str], dict]:
    stats = {"members": 0, "tags": 0, "intros": 0, "moments": 0, "portraits": 0}
    no_pet: set[int] = set()
    out = list(lines)

    def member_id(values) -> int | None:
        try:
            return int(values[0][1])
        except (TypeError, ValueError, IndexError):
            return None

    # 先收集 has_pet=无 的成员 id
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("INSERT INTO `member_profile`"):
            continue
        _, values = parse_values(stripped)
        if len(values) != MEMBER_COLUMNS:
            continue
        if values[11][1] == "无":
            member_id_value = member_id(values)
            if member_id_value is not None:
                no_pet.add(member_id_value)

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("INSERT INTO `"):
            continue
        try:
            table, values = parse_values(stripped)
        except (ValueError, IndexError):
            continue
        changed = False
        if table == "member_profile" and len(values) == MEMBER_COLUMNS:
            member_id_value = member_id(values)
            if member_id_value in no_pet:
                new_tags = clean_tags(values[15][1])
                if new_tags != values[15][1]:
                    values[15] = ("str", new_tags)
                    stats["tags"] += 1
                    changed = True
                new_intro = clean_text(values[13][1])
                if new_intro != values[13][1]:
                    values[13] = ("str", new_intro)
                    stats["intros"] += 1
                    changed = True
        elif table == "member_moment" and len(values) > MOMENT_CONTENT_INDEX:
            try:
                member_id_value = int(values[MOMENT_MEMBER_INDEX][1])
            except (TypeError, ValueError):
                member_id_value = None
            if member_id_value in no_pet:
                new_content = clean_text(values[MOMENT_CONTENT_INDEX][1], moment=True)
                if new_content != values[MOMENT_CONTENT_INDEX][1]:
                    values[MOMENT_CONTENT_INDEX] = ("str", new_content)
                    stats["moments"] += 1
                    changed = True
        elif table == "member_portrait" and len(values) > max(PORTRAIT_TEXT_INDEXES):
            try:
                member_id_value = int(values[PORTRAIT_MEMBER_INDEX][1])
            except (TypeError, ValueError):
                member_id_value = None
            if member_id_value in no_pet:
                for idx in PORTRAIT_TAG_INDEXES:
                    new_value = clean_tags(values[idx][1])
                    if new_value != values[idx][1]:
                        values[idx] = ("str", new_value)
                        changed = True
                for idx in PORTRAIT_TEXT_INDEXES:
                    new_value = clean_text(values[idx][1])
                    if new_value != values[idx][1]:
                        values[idx] = ("str", new_value)
                        changed = True
                if changed:
                    stats["portraits"] += 1
        if changed:
            ending = "\n" if line.endswith("\n") else ""
            out[index] = dump_insert(table, values) + ending
    stats["members"] = len(no_pet)
    return out, stats


def residual_report() -> list[str]:
    sys.path.insert(0, str(REPO / "eval"))
    from lib import seed  # noqa: E402
    data = seed.load_seed(REPO)
    problems: list[str] = []
    for member in data.members:
        if member.has_pet != "无":
            continue
        tags = [item for item in member.interest_tags
                if not item.startswith(NEGATIVE_PREFIX)
                and any(word in item for word in OWNERSHIP_TAGS)]
        if tags:
            problems.append(f"成员 {member.id} 仍有养宠标签：{tags}")
        if OWN_RE.search(member.self_intro) or HAVE_RE.search(member.self_intro) \
                or MY_RE.search(member.self_intro):
            problems.append(f"成员 {member.id} 简介仍有养宠句式：{member.self_intro[:60]}")
    # 动态/画像残留
    for line in SQL_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("INSERT INTO `member_moment`"):
            _, values = parse_values(stripped)
            try:
                member_id = int(values[1][1])
            except (TypeError, ValueError):
                continue
            if member_id in {m.id for m in data.members if m.has_pet == "无"}:
                if OWN_RE.search(values[2][1]) or HAVE_RE.search(values[2][1]):
                    problems.append(f"成员 {member_id} 动态仍有养宠句式：{values[2][1][:50]}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="清洗 has_pet=无 的养宠数据矛盾")
    parser.add_argument("--write", action="store_true", help="写回 01-paringbot.sql")
    parser.add_argument("--verify", action="store_true", help="只读校验无残留")
    args = parser.parse_args(argv)

    text = SQL_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    cleaned, stats = clean_lines(lines)
    changed = [i for i, (old, new) in enumerate(zip(lines, cleaned)) if old != new]
    print(f"待清理成员={stats['members']} 标签={stats['tags']} 简介={stats['intros']} "
          f"动态={stats['moments']} 画像={stats['portraits']} 改动行={len(changed)}")
    if args.verify:
        problems = residual_report()
        for problem in problems[:20]:
            print("  ", problem)
        print(f"残留问题：{len(problems)}")
        return 0 if not problems else 1
    if not args.write:
        print("dry-run：未写文件（--write 才落盘）")
        return 0
    if changed:
        SQL_PATH.write_text("".join(cleaned), encoding="utf-8")
        print(f"已写入 {SQL_PATH}")
    problems = residual_report()
    for problem in problems[:10]:
        print("  ", problem)
    print(f"写后残留问题：{len(problems)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
