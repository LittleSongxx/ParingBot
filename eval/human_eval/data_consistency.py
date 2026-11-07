#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rubric v2.2 的数据自洽规则（可重复判定，供人工/LLM 评者校准）。

只做三档：2=自洽；1=轻微缺失/含糊；0=明显矛盾。
规则与 RUBRIC_V2.md / llm_annotator.py 的 v2.2 一致：
- 养宠类兴趣 + has_pet=无 + 自述“不养/过敏/不能接受宠物”或 pet_accept=不接受 → 0；
- has_pet=有 + pet_accept=不接受 → 0；
- 仅“兴趣含养宠类 + has_pet=无”而无明确不养声明 → 1（业余爱好与饲养的歧义）；
- 关键字段缺失 → 1；否则 2。

A3 审计补充（2026-11-05）：只看 interest_tags 会漏掉自由文本里的宠物矛盾。
现在 self_intro / roommate_expectation 里出现 PET_TAGS 词：
- 若同一文本同时含 NO_PET_PHRASES（如“不养宠物，但喜欢养猫、撸猫”）→ 0：
  文本自相矛盾，是明显数据质量问题；
- 否则（只说“喜欢撸猫”但档案 has_pet=无）→ 1：文本与档案的轻微歧义。
否定写法（“不养猫”“没有养狗”）不算“提到养宠”，避免把否定句误判成矛盾。
"""
from __future__ import annotations

import re

PET_TAGS = {
    "养猫", "撸猫", "养狗", "遛狗", "养仓鼠", "仓鼠", "爬宠", "爬行动物",
    "养鱼", "水族", "宠物摄影", "猫咖", "狗咖",
}
NO_PET_PHRASES = (
    "不养宠物", "不能接受宠物", "不接受宠物", "对动物毛发过敏", "动物毛发过敏",
    "不能接受室友养宠", "不太能接受室友养宠", "不能接受室友养宠物",
)
# 宠物词的否定前缀（命中则这次提及不算“养宠声明”）
_NEGATED_PREFIX = re.compile(r"(不|没|没有|无|不想|不打算|不准备)$")


def _pref_detail(person: dict) -> dict:
    pref = person.get("preference") or {}
    if isinstance(pref, dict):
        detail = pref.get("detail") or pref
        return detail if isinstance(detail, dict) else {}
    return {}


def _pet_accept(person: dict) -> str | None:
    return _pref_detail(person).get("pet_accept")


def _text(person: dict) -> str:
    return str(person.get("self_intro") or "") + " " + str(person.get("roommate_expectation") or "")


def _tags(person: dict) -> set[str]:
    raw = person.get("interest_tags") or []
    if isinstance(raw, str):
        return set(re.split(r"[,，、\s]+", raw))
    if isinstance(raw, list):
        return set(raw)
    return set()


def _text_pet_mentions(text: str) -> set[str]:
    """自由文本里“提到养宠”的词；被“不/没/没有”否定的提及不算。"""
    mentions = set()
    for tag in PET_TAGS:
        position = text.find(tag)
        while position >= 0:
            prefix = text[max(0, position - 3):position]
            if not _NEGATED_PREFIX.search(prefix):
                mentions.add(tag)
                break
            position = text.find(tag, position + 1)
    return mentions


def _person_reasons(person: dict) -> list[str]:
    reasons: list[str] = []
    tags = _tags(person) & PET_TAGS
    has_pet = person.get("has_pet")
    accept = _pet_accept(person)
    text = _text(person)
    says_no = any(phrase in text for phrase in NO_PET_PHRASES)
    text_tags = _text_pet_mentions(text)
    mentions = sorted(tags | text_tags)
    if has_pet == "无" and mentions:
        # tags 口径沿用旧规则（兴趣含养宠 + 明确不养/pet_accept 不接受 → 0）；
        # 自由文本口径按 A3 契约：文本同时含养宠词与不养声明才是明显自相矛盾 → 0。
        severe = bool((tags and (says_no or accept == "不接受")) or (text_tags and says_no))
        if severe:
            reasons.append(f"has_pet=无 但提到{','.join(mentions)} 且有不养/过敏/不接受表述")
        else:
            reasons.append(f"提到{','.join(mentions)} 但 has_pet=无（轻微歧义）")
    elif has_pet == "有" and accept == "不接受":
        reasons.append("has_pet=有 但 pet_accept=不接受")
    if has_pet in (None, "") or "interest_tags" not in person:
        reasons.append("关键字段缺失")
    return reasons


def assess_person(person: dict) -> dict:
    """单个档案的自洽性：0=明显矛盾，1=轻微缺失/歧义，2=自洽。"""
    reasons = _person_reasons(person or {})
    severe = [reason for reason in reasons if "轻微" not in reason and "缺失" not in reason]
    if severe:
        score = 0
    elif reasons:
        score = 1
    else:
        score = 2
    return {"score": score, "reasons": reasons}


def assess(pair: dict) -> dict:
    reasons: list[str] = []
    for side in ("applicant", "candidate"):
        for reason in _person_reasons(pair.get(side) or {}):
            reasons.append(f"{side}: {reason}")
    severe = [reason for reason in reasons if "轻微" not in reason and "缺失" not in reason]
    if severe:
        score = 0
    elif reasons:
        score = 1
    else:
        score = 2
    return {"score": score, "reasons": reasons}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="按规则评估 blind_set 的 data_consistency")
    parser.add_argument("--blind", required=True, type=Path)
    args = parser.parse_args()
    rows = json.loads(args.blind.read_text(encoding="utf-8"))
    for row in rows:
        print(row.get("pair_id"), assess(row))
