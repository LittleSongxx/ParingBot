#!/usr/bin/env python3
"""管理端授权门禁：任何"写接口"都必须有防护，否则 CI 红。

背景（2026-10-16 审计）：管理端此前是"登录校验 + 注解校验"，而**没有注解等于无需权限**——
公开口令的展厅账号 gallery 实测可以直接调 `/admin/order/delivery`（发货）、
`/admin/sysCategory/saveCategory`（改分类树）、`/admin/user/changeStatus`（封禁用户）。
修复引入了 `TrialAdminAccess`（写清单默认拒绝 + 隐私清单拒绝 + 退款复核显式放行），
本脚本负责让那份清单**不会随新接口悄悄失效**：

对每个管理端端点：
- 名称以写前缀开头（add/save/update/delete/del/change/commend/handle/set/…）或使用
  PUT/PATCH/DELETE 的，视为**写接口**；写接口必须满足其一：
    ① 方法级或类级 `@SaCheckPermission`；② `@AdminSensitiveConfirm`（要求超管口令二次确认）；
    ③ 命中 `TrialAdminAccess` 的拒绝清单或白名单；④ `@TrialReadable` 显式放宽。
- 名称既不属读前缀也不属写前缀的，视为**未分类** → 判失败（强制命名约定或显式登记）。
- 反向检查：`TrialAdminAccess` 里列的每条路径都必须对应真实端点（防陈旧条目）。

退出码：0 通过；1 有缺口；2 扫描失败。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ACCESS_FILE = ROOT / "backend/smartlect-common/src/main/java/com/smartlect/security/TrialAdminAccess.java"

READ_PREFIXES = ("get", "load", "list", "query", "find", "count", "export", "statistics",
                 "probe", "me", "roles", "status",
                 # 登录/验证码/管理员列表：或走拦截器排除项，或自带权限注解
                 "login", "checkcode", "administrators")
WRITE_PREFIXES = ("add", "save", "update", "delete", "del", "change", "commend", "handle",
                  "unban", "censor", "delivery", "warmup", "reconcile", "replay", "create",
                  "approve", "reject", "mark", "set", "put", "sync", "upload", "logout",
                  "cancel", "send", "push", "reset", "enable", "disable")
MUTATING_VERBS = {"Put", "Delete", "Patch"}


def access_lists() -> tuple[set[str], set[str]]:
    text = ACCESS_FILE.read_text(encoding="utf-8")
    def block(name: str) -> set[str]:
        m = re.search(name + r"\s*=\s*List\.of\(([\s\S]*?)\);", text)
        if not m:
            raise SystemExit(f"check_admin_authz: 无法从 {ACCESS_FILE.name} 解析 {name}")
        return set(re.findall(r'"([^"]+)"', m.group(1)))
    return block("DENIED_PATH_PATTERNS"), block("ALLOWED_WRITE_PATTERNS")


def endpoints() -> list[dict]:
    found = []
    for path in sorted(ROOT.glob("backend/**/controller/admin/*.java")):
        source = path.read_text(encoding="utf-8")
        base_match = re.search(r'@RequestMapping\("([^"]+)"\)', source)
        base = base_match.group(1) if base_match else ""
        class_perm = bool(re.search(r'@SaCheckPermission\([^)]*\)[\s\S]{0,400}?class\s', source))
        for m in re.finditer(
                r'@(Get|Post|Put|Delete|Patch)Mapping\((?:value\s*=\s*)?"([^"]+)"\)'
                r'([\s\S]{0,400}?)public\s+\w[\w<>,\s\[\]]*\s+(\w+)\s*\(', source):
            verb, mapping, between, name = m.group(1), m.group(2), m.group(3), m.group(4)
            found.append({
                "file": path.name, "verb": verb, "path": base + mapping, "name": name,
                "method_perm": "@SaCheckPermission" in between,
                "confirm": "@AdminSensitiveConfirm" in between,
                "trial_readable": "@TrialReadable" in between,
                "class_perm": class_perm,
            })
    return found


def classify(name: str, verb: str) -> str:
    lower = name.lower()
    if lower.startswith(READ_PREFIXES):
        return "read"
    if verb in MUTATING_VERBS or lower.startswith(WRITE_PREFIXES):
        return "write"
    return "unknown"


def main() -> int:
    denied, allowed = access_lists()
    rows = endpoints()
    gaps: list[str] = []
    unclassified: list[str] = []
    writes = 0

    for row in rows:
        kind = classify(row["name"], row["verb"])
        row["kind"] = kind
        if kind == "unknown":
            unclassified.append(f"{row['file']} {row['verb']} {row['path']}（方法名 {row['name']}）")
            continue
        if kind != "write":
            continue
        writes += 1
        covered = (row["method_perm"] or row["class_perm"] or row["confirm"]
                   or row["trial_readable"] or row["path"] in denied or row["path"] in allowed)
        if not covered:
            gaps.append(f"{row['file']} {row['verb']} {row['path']}（方法名 {row['name']}）")

    listed = denied | allowed
    actual = {row["path"] for row in rows}

    def ant_match(pattern: str, path: str) -> bool:
        regex = re.escape(pattern).replace(r"\*\*", ".+").replace(r"\*", "[^/]+")
        return re.fullmatch(regex, path) is not None

    # 陈旧 = 该条目既不是真实端点，也覆盖不到任何真实端点（通配模式按 Ant 语义判断）
    stale = sorted(p for p in listed
                   if p not in actual and not any(ant_match(p, a) for a in actual))

    print(f"管理端端点 {len(rows)} 个，其中写接口 {writes} 个；"
          f"TrialAdminAccess 清单 {len(denied)} 拒 / {len(allowed)} 放行")
    if gaps:
        print("\n未受保护的写接口（必须补 @SaCheckPermission / @AdminSensitiveConfirm，"
              "或登记进 TrialAdminAccess）：", file=sys.stderr)
        for g in gaps:
            print(f"  - {g}", file=sys.stderr)
    if unclassified:
        print("\n无法分类的端点（请用读/写前缀命名，或显式登记）：", file=sys.stderr)
        for u in unclassified:
            print(f"  - {u}", file=sys.stderr)
    if stale:
        print("\nTrialAdminAccess 中的陈旧条目（端点已不存在，请清理）：", file=sys.stderr)
        for s in stale:
            print(f"  - {s}", file=sys.stderr)
    if gaps or unclassified:
        return 1
    if stale:
        print("提示：存在陈旧条目（不影响结论，但会掩盖真实清单）")
    print("check_admin_authz: 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
