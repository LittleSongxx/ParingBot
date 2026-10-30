#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0 AI 能力评测入口。

用法：
  python eval/run_eval.py --fixtures                 # 校验 40 条 golden case 的参考输出
  python eval/run_eval.py --outputs eval/outputs     # 校验真实模型输出（<case-id>.json）
  python eval/run_eval.py --fixtures --bad eval/fixtures/bad
  python eval/run_eval.py --fixtures --json eval/report.json

设计原则：
- 只用标准库，CI 直接跑，不需要数据库/模型 Key；
- golden case 自带 reference，先证明「校验器能认真实输出、也能挡住坏输出」；
- 接真实模型时用 --outputs 指向模型输出目录，用同一套规则评分；
- 退出码：有硬失败返回 1，全部通过返回 0。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from schema import validate  # noqa: E402


def load_cases(root: Path) -> list[dict]:
    cases: list[dict] = []
    for folder in ("profile_coach", "match_brief"):
        case_dir = root / folder
        if not case_dir.exists():
            continue
        for path in sorted(case_dir.glob("*.json")):
            with path.open(encoding="utf-8") as handle:
                case = json.load(handle)
            case.setdefault("scene", folder)
            case["_path"] = str(path.relative_to(root.parent))
            case["_file"] = path.name
            cases.append(case)
    seen = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id:
            raise SystemExit(f"用例缺少 id：{case['_path']}")
        if case_id in seen:
            raise SystemExit(f"用例 id 重复：{case_id}")
        seen.add(case_id)
    return cases


def output_for_fixture(case: dict) -> dict | None:
    return case.get("reference")


def output_for_file(case: dict, outputs: Path) -> dict | None:
    path = outputs / f"{case['id']}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def run_cases(cases: list[dict], outputs: Path | None) -> tuple[list[dict], int, int]:
    results: list[dict] = []
    passed = failed = 0
    for case in cases:
        output = output_for_file(case, outputs) if outputs else output_for_fixture(case)
        if output is None:
            errors = ["没有找到输出文件" if outputs else "用例缺少 reference"]
        else:
            errors = validate(case["scene"], output, case)
        ok = not errors
        passed += 1 if ok else 0
        failed += 0 if ok else 1
        results.append({"id": case["id"], "scene": case["scene"],
                        "title": case.get("title", ""), "ok": ok, "errors": errors})
    return results, passed, failed


def run_bad(bad_dir: Path, cases: list[dict]) -> list[dict]:
    by_id = {case["id"]: case for case in cases}
    results: list[dict] = []
    for path in sorted(bad_dir.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            item = json.load(handle)
        case = by_id.get(item.get("case_id"))
        if case is None:
            results.append({"file": path.name, "ok": False,
                            "detail": "bad fixture 指向不存在的 case"})
            continue
        errors = validate(case["scene"], item.get("output"), case)
        results.append({"file": path.name, "ok": bool(errors),
                        "detail": "正确拦截" if errors else "本应拦截但没有发现错误",
                        "errors": errors[:2]})
    return results


def print_results(results: list[dict], passed: int, failed: int) -> None:
    for row in results:
        flag = "PASS" if row["ok"] else "FAIL"
        print(f"[{flag}] {row['id']:<28} {row['title']}")
        for error in row["errors"][:4]:
            print(f"       - {error}")
    print(f"\n合计 {passed + failed} 条：{passed} 通过，{failed} 失败")


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 AI 能力评测（离线 fixture / 真实输出）")
    parser.add_argument("--cases", default=str(ROOT / "cases"), help="用例目录")
    parser.add_argument("--fixtures", action="store_true", help="校验用例内置 reference 输出")
    parser.add_argument("--outputs", type=Path, help="真实模型输出目录（<case-id>.json）")
    parser.add_argument("--bad", type=Path, help="应被拦截的坏输出目录（自检）")
    parser.add_argument("--json", type=Path, help="把结果写成 JSON 报告")
    args = parser.parse_args(argv)

    if not args.fixtures and not args.outputs:
        args.fixtures = True
    if args.fixtures and args.outputs:
        parser.error("--fixtures 与 --outputs 二选一")

    cases = load_cases(Path(args.cases))
    if not cases:
        print("没有找到用例：eval/cases/ 为空", file=sys.stderr)
        return 2
    results, passed, failed = run_cases(cases, args.outputs)
    print_results(results, passed, failed)

    bad_failed = 0
    bad_results: list[dict] = []
    if args.bad:
        bad_results = run_bad(args.bad, cases)
        bad_failed = sum(1 for row in bad_results if not row["ok"])
        print("\n坏输出自检：")
        for row in bad_results:
            print(f"  [{'PASS' if row['ok'] else 'FAIL'}] {row['file']}: {row['detail']}")
            for error in row.get("errors") or []:
                print(f"       - {error}")

    if args.json:
        write_report(args.json, {
            "total": len(cases), "passed": passed, "failed": failed,
            "by_scene": {
                scene: {
                    "total": sum(1 for row in results if row["scene"] == scene),
                    "passed": sum(1 for row in results if row["scene"] == scene and row["ok"]),
                }
                for scene in ("profile_coach", "match_brief")
            },
            "results": results,
            "bad_self_test": {"failed_expected": bad_failed, "results": bad_results},
        })

    return 1 if failed or bad_failed else 0


if __name__ == "__main__":
    sys.exit(main())
