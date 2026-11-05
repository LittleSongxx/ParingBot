#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测体系自检（test the test）：防止指标造假/门禁被放松/场景硬编码。

CI 与本地都可运行，不联网、不连 DB、不调模型。检查：
1. 冻结文件、base 供给池、v4 场景、标签复算全部一致；
2. 产品/评测运行代码里没有 V3_xx/V4_xx 场景硬编码或场景专属分支；
3. 报告门禁探针：干净通过、单场景归零失败、负向断言失败、baseline hash 漂移、
   publish 缺成本/judge、token 超预算——必须按设计 fail-closed；
4. BASELINE 仍是 schema v2 且 max_failures_delta=0（没有被悄悄放松）；
5. live-eval 没有自动重算 oracle，冻结校验仍带 --verify；
6. judge 材料白名单（delivered_rank/screen_score/evidence/A_role 等不进入材料）；
7. 内容 judge 仪器校验（已知坏样本能被识别、天花板检测可用）。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import re
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import check_freeze  # noqa: E402
import report  # noqa: E402
from content_quality import ceiling_effect, corrupt_items  # noqa: E402
from pairwise_quality import FORBIDDEN_MATERIAL_KEYS, assert_safe_material, safe_person  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SCENARIOS = ROOT / "frozen" / "v3" / "scenarios.json"
LABELS = ROOT / "frozen" / "v3" / "labels.json"
MANIFEST = ROOT / "frozen" / "v3" / "MANIFEST.json"
BASELINE = ROOT / "frozen" / "v3" / "BASELINE.json"
FROZEN = ROOT / "frozen" / "v3"
V4_MANIFEST = ROOT / "frozen" / "v4" / "MANIFEST.json"
LIVE_WORKFLOW = REPO / ".github" / "workflows" / "live-eval.yml"

CHECKS: list[tuple[str, bool, str]] = []


def _strip_comments(text: str) -> str:
    """去掉 # 注释（保留字符串字面量），避免注释里的示例被误判为硬编码。"""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return " ".join(tok.string for tok in tokens if tok.type != tokenize.COMMENT)
    except tokenize.TokenError:
        return text


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_scenarios() -> list[dict]:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def _target(scenario: dict, requested: int) -> int:
    expect = scenario.get("expect") or {}
    target = expect.get("target")
    if target is None:
        capacity = scenario.get("ex_ante_capacity") or {}
        eligible = (capacity.get("eligible_unbounded")
                    or expect.get("ex_ante_unbounded")
                    or capacity.get("eligible")
                    or expect.get("ex_ante_eligible"))
        target = min(requested, int(eligible)) if eligible else requested
    return max(0, int(target))


def _matrix_payload() -> dict:
    return json.loads((FIX / "matrix" / "scenario-matrix-test" / "matrix.json").read_text(encoding="utf-8"))


def _write_matrix(tmp: Path, payload: dict) -> Path:
    directory = tmp / "scenario-matrix-audit"
    directory.mkdir()
    (directory / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return tmp


def _baseline_payload() -> dict:
    matrix = _matrix_payload()
    targets = {item["key"]: _target(item, 8) for item in _frozen_scenarios() if item.get("run")}
    per_scenario = {}
    for scenario in matrix["scenarios"]:
        key = scenario.get("key")
        if key not in targets:
            continue
        delivered = [int(run.get("delivered") or 0) for run in (scenario.get("runs") or [])]
        if not delivered:
            continue
        per_scenario[key] = {
            "delivered": delivered,
            "target": targets[key],
            "target_attainment": round(min(delivered[-1] / targets[key], 1.0), 4) if targets[key] else 0.0,
        }
    return {
        "schema_version": 2,
        "protocol_version": "v3-2026-11-04",
        "labels_sha256": _sha(LABELS),
        "scenarios_sha256": _sha(SCENARIOS),
        "source": {"code_commit": "self-check", "run_id": "self-check"},
        "model_configs": [{"purpose": "审核", "model_name": "deepseek-flash"}],
        "db_profile": "eval",
        "failures": 0,
        "per_scenario": per_scenario,
        "regression": {"max_failures_delta": 0, "target_margin": 0.0351},
    }


def _write_baseline(tmp: Path, payload: dict | None = None) -> Path:
    path = tmp / "BASELINE.json"
    path.write_text(json.dumps(payload or _baseline_payload(), ensure_ascii=False), encoding="utf-8")
    return path


def _args(tmp: Path, matrix: Path, baseline: Path, extra: list[str] | None = None) -> list[str]:
    return [
        "--bundle", str(FIX / "synthetic_bundle.json"),
        "--matrix", str(matrix),
        "--matrix-stamp", "audit",
        "--labels", str(LABELS),
        "--scenarios", str(SCENARIOS),
        "--manifest", str(MANIFEST),
        "--mode", "verify",
        "--baseline", str(baseline),
    ] + list(extra or [])


def _run_report(args: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return report.main(args)


def _check(name: str):
    def decorator(fn):
        try:
            detail = fn() or ""
            CHECKS.append((name, True, str(detail)))
        except Exception as exc:  # noqa: BLE001
            CHECKS.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn
    return decorator


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


@_check("冻结文件与供给池")
def check_frozen():
    errors = check_freeze.check_manifest(FROZEN)
    errors += check_freeze.scan_repo_supply()
    _assert(not errors, errors)
    return "manifest/base sql/pool digest/eval sql 全一致"


@_check("v4 冻结场景")
def check_v4():
    import check_v4_freeze
    errors = check_v4_freeze.check()
    _assert(not errors, errors)
    manifest = json.loads(V4_MANIFEST.read_text(encoding="utf-8"))
    _assert(manifest["labels"]["status"] == "pending", "v4 labels 应保持 pending（未人工标注前不得接门禁）")
    return "v4 sha/40+8/target/文本自洽/pool 指纹一致"


@_check("标签可复算")
def check_labels():
    import build_frozen_labels
    _assert(build_frozen_labels.verify(None, REPO) == 0, "labels 与 base SQL/场景重算不一致")
    return "labels.json 可由 base SQL + 场景确定性复算"


@_check("无场景硬编码")
def check_no_scenario_hardcode():
    """只扫“产品/评测运行代码”；build/check 脚本的文档字符串允许举例 V4_01。"""
    pattern = re.compile(r"\b(?:V3_\d{2}|V4_\d{2})\b")
    runtime_files = list((REPO / "backend").rglob("*.py")) + [
        ROOT / name for name in (
            "report.py", "run_matrix.py", "build_bundle.py", "quality_checks.py",
            "safety_checks.py", "judge.py", "pairwise_quality.py", "pairwise_ranking.py",
            "content_quality.py", "analyze_pilot.py", "quality_scorecard.py",
            "warm_candidate_portraits.py",
        )
    ]
    files = [path for path in runtime_files if path.is_file()]
    hits = []
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        if "/tests/" in rel or rel.startswith("eval/tests/"):
            continue
        text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        for match in pattern.finditer(text):
            hits.append(f"{rel}:{match.group(0)}")
    _assert(not hits, f"产品/评测运行代码出现场景硬编码：{hits[:8]}")
    return f"{len(files)} 个产品/评测运行脚本无场景硬编码"


@_check("门禁探针：干净通过")
def check_gate_pass():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        matrix = _write_matrix(tmp, _matrix_payload())
        baseline = _write_baseline(tmp)
        _assert(_run_report(_args(tmp, matrix, baseline)) == 0, "干净数据应通过")
    return "fixture verify 通过"


@_check("门禁探针：单场景归零失败")
def check_gate_zero():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        payload = _matrix_payload()
        for scenario in payload["scenarios"]:
            if scenario["key"] == "V3_01":
                scenario["runs"][0]["delivered"] = 0
        matrix = _write_matrix(tmp, payload)
        baseline = _write_baseline(tmp)
        _assert(_run_report(_args(tmp, matrix, baseline)) == 1, "单场景归零必须失败")
    return "V3_01=0 被门禁拦截"


@_check("门禁探针：负向断言失败")
def check_gate_negative():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        payload = _matrix_payload()
        for scenario in payload["scenarios"]:
            if scenario["key"] == "V3_09":
                scenario["expectation_ok"] = False
        matrix = _write_matrix(tmp, payload)
        baseline = _write_baseline(tmp)
        _assert(_run_report(_args(tmp, matrix, baseline)) == 1, "负向未阻断必须失败")
    return "V3_09 负向断言失败被拦截"


@_check("门禁探针：baseline hash 漂移")
def check_gate_hash():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        matrix = _write_matrix(tmp, _matrix_payload())
        payload = _baseline_payload()
        payload["labels_sha256"] = "deadbeef"
        baseline = _write_baseline(tmp, payload)
        _assert(_run_report(_args(tmp, matrix, baseline)) == 1, "baseline hash 不符必须失败")
    return "labels hash 漂移被拦截"


@_check("门禁探针：publish 缺成本/judge")
def check_gate_publish():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        matrix = _write_matrix(tmp, _matrix_payload())
        baseline = _write_baseline(tmp)
        _assert(_run_report(_args(tmp, matrix, baseline) + ["--publish"]) == 1, "publish 缺成本/judge 必须失败")
    return "publish 缺成本/judge 被拦截"


@_check("门禁探针：token 超预算")
def check_gate_token():
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        matrix = _write_matrix(tmp, _matrix_payload())
        baseline = _write_baseline(tmp)
        bundle = json.loads((FIX / "synthetic_bundle.json").read_text(encoding="utf-8"))
        bundle["runs"][0]["run"]["prompt_tokens"] = 999999
        bundle_path = tmp / "bundle-token.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        args = _args(tmp, matrix, baseline) + ["--max-tokens", "1"]
        args[args.index(str(FIX / "synthetic_bundle.json"))] = str(bundle_path)
        _assert(_run_report(args) == 1, "token 超预算必须失败")
    return "token 预算 fail-closed"


@_check("BASELINE 未被放松")
def check_baseline_not_weakened():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    _assert(baseline.get("schema_version") == 2, "BASELINE 应为 schema v2")
    _assert(int((baseline.get("regression") or {}).get("max_failures_delta", 0)) == 0,
            "max_failures_delta 不得从 0 放松")
    _assert(baseline.get("protocol_version") == json.loads(MANIFEST.read_text(encoding="utf-8"))["protocol_version"],
            "BASELINE protocol 必须与 MANIFEST 一致")
    _assert("per_scenario" in baseline and baseline["per_scenario"], "BASELINE 缺 per_scenario")
    return "schema v2 / protocol / per_scenario / failures_delta=0"


@_check("无自动重算 oracle")
def check_no_auto_refresh():
    text = LIVE_WORKFLOW.read_text(encoding="utf-8")
    _assert("refresh_golden_labels" not in text, "live-eval 不得包含自动重算标签")
    _assert("build_frozen_labels.py --verify" in text, "live-eval 应显式跑 build_frozen_labels --verify")
    return "live-eval 只读冻结标签，显式 verify"


@_check("judge 材料白名单")
def check_judge_material():
    dirty = {"nickname": "x", "delivered_rank": 1, "screen_score": 99,
             "evidence": ["同门店"], "A_role": "delivered"}
    clean = safe_person(dirty)
    _assert(not (set(clean) & set(FORBIDDEN_MATERIAL_KEYS)), f"safe_person 泄漏：{set(clean) & set(FORBIDDEN_MATERIAL_KEYS)}")
    _assert(not any(key.endswith("_role") for key in clean), "safe_person 不得保留 *_role")
    try:
        assert_safe_material({"A": dirty})
    except ValueError:
        pass
    else:
        raise AssertionError("assert_safe_material 未拦截脏材料")
    return "禁字段与角色标签全部被拦截"


@_check("内容 judge 仪器校验")
def check_content_instrument():
    items = [{"item_id": "A1", "role": "applicant",
              "profile": {"has_pet": "有", "smoking": "经常"},
              "portrait": {"summary": "作息规律"}}]
    anchors = corrupt_items(items, 1)
    _assert(anchors[0]["item_id"] == "A1-corrupt", "corrupt_items 未生效")
    _assert(anchors[0]["profile"]["has_pet"] == "无", "锚点 profile 未改坏")
    _assert(items[0]["profile"]["has_pet"] == "有", "corrupt_items 不得修改原 item")
    _assert(ceiling_effect([5, 5, 5]) is True, "天花板检测应识别全 5")
    _assert(ceiling_effect([5, 4, 5]) is False, "有区分度不应误报天花板")
    return "已知坏锚点/原 item 不变/天花板检测可用"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="评测体系自检（test the test）")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    failed = [name for name, ok, _ in CHECKS if not ok]
    for name, ok, detail in CHECKS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}：{detail}")
    print(f"\n自查：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())