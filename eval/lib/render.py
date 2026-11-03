#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把离线评测结果渲染成 Markdown（纯标准库）。

两个入口：

* render_report(result)：回归报告/评测报告。字段不认识也不会炸——标量进表格、
  列表进条目、其余按键名顺序兜底，评测工具可以逐步加字段而不用改渲染层。
* render_matrix(records)：场景矩阵。每个场景一行，优先展示 key/账号/标题/状态、
  交付人数与运行轮次；带 runs 的场景自动汇总交付数。
"""
from __future__ import annotations

from typing import Iterable

# 报告里出现这些字样的浮点数按百分比展示
_PERCENT_HINTS = ("rate", "ratio", "precision", "recall", "ndcg", "coverage", "agreement")

# 场景矩阵的列顺序与中文表头
_MATRIX_COLUMNS = (
    ("key", "场景"),
    ("account", "账号"),
    ("title", "标题"),
    ("status", "状态"),
    ("readiness", "就绪"),
    ("runs", "轮次"),
    ("delivered", "交付"),
    ("requested", "要求"),
    ("delivered_avg", "平均交付"),
)

_KNOWN_SECTIONS = (
    ("delivery", "交付"),
    ("agreement", "一致性（监控指标，不作门禁）"),
    ("ndcg", "NDCG（监控指标，不作门禁）"),
    ("judge", "独立评审"),
    ("quality_checks", "质量检查"),
    ("safety", "安全检查"),
    ("cost", "成本"),
    ("latency", "延迟"),
    ("gates", "门禁"),
)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell(value, key: str = "") -> str:
    """把一个值渲染成单元格文本。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if _is_number(value):
        if any(hint in key.lower() for hint in _PERCENT_HINTS):
            return f"{value:.2%}"
        if isinstance(value, float):
            return f"{value:.4g}"
        return str(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return "、".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{name}={_cell(item, name)}" for name, item in value.items())
    return str(value).replace("\n", " ").strip() or "—"


def _table(headers: Iterable[str], rows: Iterable[Iterable]) -> list[str]:
    rows = list(rows)
    if not rows:
        return []
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return lines


def _scalar_table(mapping: dict, key_prefix: str = "") -> list[str]:
    rows = [(name, value) for name, value in mapping.items() if not isinstance(value, (dict, list))]
    if not rows:
        return []
    return _table(("项目", "值"), [(name, _cell(value, f"{key_prefix}{name}")) for name, value in rows])


def _rows_of(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("rows", "per_scenario", "items", "checks", "issues", "reasons"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def _dict_table(rows: list[dict]) -> list[str]:
    """按行渲染字典列表：列取所有行出现过的标量键，顺序按首次出现。"""
    if not rows:
        return []
    columns: list[str] = []
    for row in rows:
        for name, value in row.items():
            if name not in columns and not isinstance(value, (dict, list)):
                columns.append(name)
    if not columns:
        return []
    return _table(columns, [[row.get(name) for name in columns] for row in rows])


def render_report(result: dict) -> str:
    """把一份评测/回归结果字典渲染成 Markdown 报告。"""
    data = result or {}
    title = data.get("title") or "评测报告"
    lines = [f"# {title}", ""]
    meta = data.get("meta")
    if isinstance(meta, dict) and meta:
        lines.append("## 指纹")
        lines.append("")
        lines.extend(_scalar_table(meta))
        for name, value in meta.items():
            if isinstance(value, dict) and value:
                lines.append("")
                lines.append(f"**{name}**")
                lines.append("")
                lines.extend(_scalar_table(value, name + "."))
        lines.append("")

    gates = data.get("gates")
    if isinstance(gates, dict):
        failed = gates.get("failed")
        verdict = "失败" if failed else "通过"
        lines.append(f"## 门禁：{verdict}")
        lines.append("")
        reasons = gates.get("reasons") or []
        if reasons:
            lines.extend(f"- {_cell(reason)}" for reason in reasons)
        else:
            lines.append("- 无失败项")
        extra = {name: value for name, value in gates.items()
                 if name not in ("failed", "reasons") and not isinstance(value, (dict, list))}
        if extra:
            lines.append("")
            lines.extend(_scalar_table(extra, "gates."))
        lines.append("")

    section_keys = {name for name, _label in _KNOWN_SECTIONS}
    section_keys |= {"title", "meta", "gates"}
    for name, label in _KNOWN_SECTIONS:
        value = data.get(name)
        if value is None:
            continue
        lines.append(f"## {label}")
        lines.append("")
        if isinstance(value, dict):
            lines.extend(_scalar_table(value, name + "."))
            rows = _rows_of(value)
            if rows:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.extend(_dict_table(rows))
        elif isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                lines.extend(_dict_table(rows))
            else:
                lines.extend(f"- {_cell(item)}" for item in value)
        else:
            lines.append(_cell(value))
        lines.append("")

    for name, value in data.items():
        if name in section_keys:
            continue
        lines.append(f"## {name}")
        lines.append("")
        if isinstance(value, dict):
            lines.extend(_scalar_table(value, name + ".") or [f"```json\n{value}\n```"])
            rows = _rows_of(value)
            if rows:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.extend(_dict_table(rows))
        elif isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            lines.extend(_dict_table(rows) if rows else [f"- {_cell(item)}" for item in value])
        else:
            lines.append(_cell(value))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _matrix_row(item: dict) -> dict:
    """把一条场景记录压平成矩阵表格的一行。"""
    row: dict = {}
    for name, value in item.items():
        if isinstance(value, (dict, list)):
            continue
        row[name] = value
    expect = item.get("expect")
    if isinstance(expect, dict):
        if expect.get("blocker"):
            row.setdefault("status", "预期阻断：" + str(expect["blocker"]))
        elif expect.get("can_run") is False:
            row.setdefault("status", "预期不可运行")
    elif isinstance(expect, str) and "status" not in row:
        row["status"] = expect
    readiness = item.get("readiness")
    if isinstance(readiness, dict):
        blocker = readiness.get("blocker")
        if isinstance(blocker, dict):
            row["readiness"] = blocker.get("label") or blocker.get("key") or "阻断"
        elif blocker:
            row["readiness"] = str(blocker)
        elif readiness.get("can_run") is not None:
            row["readiness"] = "通过" if readiness.get("can_run") else "阻断"
    elif isinstance(readiness, str):
        row["readiness"] = readiness
    runs = item.get("runs")
    if isinstance(runs, list) and runs:
        run_rows = [run for run in runs if isinstance(run, dict)]
        row["runs"] = len(run_rows)
        delivered = []
        requested = []
        statuses = []
        for run in run_rows:
            count = run.get("delivered")
            if isinstance(count, (int, float)):
                delivered.append(int(count))
            elif isinstance(count, (list, tuple)):
                delivered.append(len(count))
            asked = run.get("requested") or run.get("deliver_count")
            if isinstance(asked, (int, float)):
                requested.append(int(asked))
            status = run.get("run_status") or run.get("status")
            if status and status not in statuses:
                statuses.append(status)
        if delivered:
            row["delivered"] = sum(delivered)
            row["delivered_avg"] = round(sum(delivered) / len(delivered), 2)
        if requested:
            row["requested"] = sum(requested)
        if statuses and "status" not in row:
            row["status"] = "、".join(statuses)
    return row


def render_matrix(records) -> str:
    """把场景矩阵记录渲染成 Markdown：每个场景一行。"""
    items = records
    if isinstance(records, dict):
        for key in ("records", "scenarios", "items"):
            if isinstance(records.get(key), list):
                items = records[key]
                break
        else:
            items = list(records.values())
    rows = [_matrix_row(item) for item in (items or []) if isinstance(item, dict)]
    lines = ["# 场景矩阵", ""]
    if not rows:
        lines.append("没有场景记录。")
        return "\n".join(lines) + "\n"
    columns = [(name, label) for name, label in _MATRIX_COLUMNS
               if any(name in row for row in rows)]
    # 记录里出现但没在固定列里的标量字段，补在后面
    for row in rows:
        for name in row:
            if name not in {column for column, _label in columns}:
                columns.append((name, name))
    table_rows = [[row.get(name) for name, _label in columns] for row in rows]
    lines.extend(_table([label for _name, label in columns], table_rows))
    lines.append("")
    delivered = [row.get("delivered") for row in rows if _is_number(row.get("delivered"))]
    if delivered:
        lines.append(f"场景数 {len(rows)}，交付合计 {sum(delivered)} 人。")
    else:
        lines.append(f"场景数 {len(rows)}。")
    return "\n".join(lines) + "\n"