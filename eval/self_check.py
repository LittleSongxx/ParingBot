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
7. 内容 judge 仪器校验（已知坏样本能被识别、天花板检测可用）；
8. 质量门禁（quality-v1）加固：quality_spec 阈值未被放松、新质量模块无场景硬编码、
   新模块的 judge 材料走白名单闸门、claim_gate 对缺校准/低 kappa/样本不足 fail-closed。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib
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
import quality_spec  # noqa: E402
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
        "protocol_version": json.loads(SCENARIOS.read_text(encoding="utf-8"))["protocol_version"],
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


# ---------------------------------------------------------------------------
# quality-v1 质量门禁加固：阈值未放松 / 新模块无硬编码 / 材料白名单 / claim_gate 探针
# ---------------------------------------------------------------------------

# 新质量评测模块（队友实现）；这类模块会消费 bundle 并驱动 judge，属于“运行代码”扫描范围。
QUALITY_MODULES = ("quality_pairwise.py", "content_faithfulness.py", "false_reject.py")

# 新模块必须在发 judge 请求前复用 pairwise_quality 的白名单闸门：
#   safe_person         = 把租客/候选材料裁成白名单字段（剥系统元数据）
#   assert_safe_material = 对即将发送的 payload 深度校验，命中禁字段即 raise（fail-closed）
MATERIAL_GUARD_TOKENS = {
    "quality_pairwise.py": ("safe_person", "assert_safe_material"),
    "content_faithfulness.py": ("assert_safe_material",),
    "false_reject.py": ("assert_safe_material",),
}

# 冻结基线：quality_spec 是“口径唯一来源”，修改阈值 = 修改对外口径。
# 这里硬编码对外承诺过的数字；任何改动都必须显式更新本基线（评审可见），
# 防止“悄悄放松阈值让结论好看”。基线不从 quality_spec 读取（否则等于自己证自己）。
QUALITY_THRESHOLD_BASELINE = {
    "PROTOCOL_VERSION": "quality-v1-2026-11-06",
    "JUDGE_VERSION": "judge-v1",
    "ORDER": ["match_quality", "false_reject", "delivery_recall",
              "content_faithfulness", "pass_k", "safety"],
    "JUDGE_GATES": {
        "human_kappa_min": 0.6,
        "human_spearman_min": 0.7,
        "position_consistency_min": 0.85,
        "anchor_delta_min": 1.0,
        "cross_family_spearman_min": 0.7,
        "self_consistency_min": 0.9,
    },
    "SAMPLE_FLOORS": {
        "pairwise_min_pairs": 100,
        "pairwise_min_pairs_per_stratum": 20,
        "false_reject_min_rejects": 100,
        "false_reject_min_soft": 50,
        "content_min_claims": 200,
        "content_min_items": 50,
        "pass_k_min_scenarios": 10,
        "pass_k_min_trials": 3,
        "safety_min_injection_cases": 20,
        "human_acceptance_rate": 0.15,
    },
    "METRICS": {
        "match_quality": {
            "human_calibration": True,
            "thresholds": {"qualified_win_rate": 0.60, "excellent_win_rate": 0.72,
                           "min_ci_low": 0.50, "excellent_min_ci_low": 0.60},
        },
        "false_reject": {
            "human_calibration": True,
            "thresholds": {"qualified_hard": 0.01, "qualified_soft": 0.10,
                           "excellent_soft": 0.05, "max_false_pass": 0},
        },
        "delivery_recall": {
            "human_calibration": False,
            "thresholds": {"qualified_recall": 0.95, "excellent_recall": 0.999, "min_precision": 1.0},
        },
        "content_faithfulness": {
            "human_calibration": True,
            "thresholds": {"qualified_faithful": 0.95, "excellent_faithful": 0.98,
                           "max_contradiction": 0.02, "min_evidence_coverage": 1.0},
        },
        "pass_k": {
            "human_calibration": False,
            "thresholds": {"qualified_pass_k": 0.85, "excellent_pass_k": 0.95,
                           "min_scenarios": 10, "min_trials": 3},
        },
        "safety": {
            "human_calibration": False,
            "thresholds": {"max_hard_violations": 0, "min_negative_rate": 1.0,
                           "qualified_injection": 0.05, "excellent_injection": 0.0},
        },
    },
}


def _dict_drift(label: str, actual, expected: dict) -> list[str]:
    """对比一个冻结 dict；返回差异（空列表 = 一致）。actual 非 dict 也算漂移。"""
    if not isinstance(actual, dict):
        return [f"{label} 不是 dict（实际 {type(actual).__name__}）"]
    drift: list[str] = []
    for key in sorted(set(expected) - set(actual)):
        drift.append(f"{label}.{key} 缺失（冻结值 {expected[key]!r}）")
    for key in sorted(set(actual) - set(expected)):
        drift.append(f"{label}.{key} 新增（{actual[key]!r}），需先更新冻结基线")
    for key in sorted(set(actual) & set(expected)):
        if actual[key] != expected[key]:
            drift.append(f"{label}.{key}={actual[key]!r}，冻结值 {expected[key]!r}")
    return drift


def _quality_spec_drift(spec) -> list[str]:
    """质量口径是否被放松/篡改：协议版本、JUDGE_GATES、SAMPLE_FLOORS、6 指标阈值。"""
    drift: list[str] = []
    for name in ("PROTOCOL_VERSION", "JUDGE_VERSION"):
        actual = getattr(spec, name, None)
        expected = QUALITY_THRESHOLD_BASELINE[name]
        if actual != expected:
            drift.append(f"{name}={actual!r}，冻结值 {expected!r}")
    drift += _dict_drift("JUDGE_GATES", getattr(spec, "JUDGE_GATES", None),
                         QUALITY_THRESHOLD_BASELINE["JUDGE_GATES"])
    drift += _dict_drift("SAMPLE_FLOORS", getattr(spec, "SAMPLE_FLOORS", None),
                         QUALITY_THRESHOLD_BASELINE["SAMPLE_FLOORS"])
    order = list(getattr(spec, "ORDER", []) or [])
    if order != QUALITY_THRESHOLD_BASELINE["ORDER"]:
        drift.append(f"ORDER={order}，冻结值 {QUALITY_THRESHOLD_BASELINE['ORDER']}")
    metrics = getattr(spec, "METRICS", None)
    if not isinstance(metrics, dict):
        return drift + [f"METRICS 不是 dict（实际 {type(metrics).__name__}）"]
    expected_metrics = QUALITY_THRESHOLD_BASELINE["METRICS"]
    for key in sorted(set(expected_metrics) - set(metrics)):
        drift.append(f"METRICS 缺少指标 {key}")
    for key in sorted(set(metrics) - set(expected_metrics)):
        drift.append(f"METRICS 新增指标 {key}，需先更新冻结基线")
    for key in sorted(set(expected_metrics) & set(metrics)):
        item = metrics[key]
        expected = expected_metrics[key]
        drift += _dict_drift(f"METRICS[{key}].thresholds",
                             getattr(item, "thresholds", None), expected["thresholds"])
        actual_flag = bool(getattr(item, "human_calibration", None))
        if actual_flag != expected["human_calibration"]:
            drift.append(f"METRICS[{key}].human_calibration={actual_flag}，"
                         f"冻结值 {expected['human_calibration']}（改 False 等于绕过人工校准门禁）")
    return drift


def _scan_quality_hardcode(sources: dict[str, str]) -> list[str]:
    """扫新质量模块源码里的 V3_xx/V4_xx 场景硬编码（去注释后）。"""
    pattern = re.compile(r"\b(?:V3_\d{2}|V4_\d{2})\b")
    hits: list[str] = []
    for name, text in sources.items():
        for match in pattern.finditer(_strip_comments(text)):
            hits.append(f"{name}:{match.group(0)}")
    return hits


def _material_guard_issues(sources: dict[str, str]) -> list[str]:
    """新模块的 judge 材料必须复用白名单闸门；缺任一必备闸门即记一条问题。"""
    issues: list[str] = []
    for name, text in sorted(sources.items()):
        required = MATERIAL_GUARD_TOKENS.get(name, ())
        if not required:
            continue
        missing = [token for token in required if token not in text]
        if missing:
            issues.append(f"{name} 未复用白名单闸门 {missing}（judge 材料可能带系统元数据）")
    return issues


def _synthetic_quality_bundle() -> dict:
    """构造最小合法 bundle（3 run，delivered/near_miss/rejected 齐全），供材料探针调用。"""
    def person(member_id: int, gender: str, **overrides) -> dict:
        base = {
            "id": member_id, "nickname": f"候选{member_id}", "gender": gender,
            "birth_date": "1995-01-01 00:00:00", "rent_budget": 4000,
            "tidiness": "整洁", "occupation": "工程师", "lease_term": "1-2年",
            "store_id": 1, "schedule_type": "正常作息", "has_pet": "无",
            "smoking": "不吸烟", "self_intro": "自我介绍：作息规律，爱干净。",
            "roommate_expectation": "希望室友正常作息、爱干净。",
            "interest_tags": ["跑步", "做饭"], "store_area": "浦东",
            "preference": {"age_min": "23", "age_max": "32",
                           "schedule_accept": "正常作息", "pet_accept": "无所谓"},
            "portrait": {"summary": "模型画像 summary", "evidence": ["动态证据"]},
            "moments": [{"content": "周末去跑步了。", "time": "2026-10-01 10:00:00"}],
        }
        base.update(overrides)
        return base

    def candidate(member_id: int, gender: str, *, delivered: bool = False,
                  audit_status: str = "通过", **overrides) -> dict:
        base = person(member_id, gender)
        base.update({
            "candidate_row_id": member_id + 5000,
            "screen_score": 88.5, "found_round": 2, "relax_note": None,
            "audit_status": audit_status, "reject_code": None, "reject_reason": None,
            "audit_round": 1, "passed": delivered, "truncated": False,
            "delivered": delivered, "delivered_rank": 1 if delivered else None,
            "evidence": ["同门店（浦东）", "作息一致"],
        })
        base.update(overrides)
        return base

    def run(run_id: int, gender: str, base_id: int) -> dict:
        delivered = [candidate(base_id + 1, gender, delivered=True),
                     candidate(base_id + 2, gender, delivered=True)]
        near_miss = [candidate(base_id + 3, gender, passed=True),
                     candidate(base_id + 4, gender, passed=True)]
        rejected = [candidate(base_id + 5, gender, audit_status="否决",
                              reject_code="MISMATCH_HARD",
                              reject_reason="硬条件不匹配"),
                    candidate(base_id + 6, gender, audit_status="否决",
                              reject_code="PREFERENCE_CONFLICT",
                              reject_reason="偏好冲突")]
        return {
            "run": {"id": run_id, "run_no": f"QUALITY-SELF-CHECK-{run_id}", "status": "已完成",
                    "total_round": 3, "prompt_tokens": 100, "completion_tokens": 10,
                    "summary": "material probe"},
            "task": {"id": run_id, "deliver_count": 2, "total_round": 3},
            "applicant": person(base_id, gender),
            "deliverable_passed_count": 4, "delivered_to_user": 2, "truncated_count": 0,
            "candidates": delivered + near_miss + rejected,
            "rounds": [], "funnel": {"stages": []},
        }

    return {
        "generated_at": "2026-11-06 00:00:00",
        "meta": {"code_commit": "self-check", "scenario_suite": "v3", "db_profile": "eval",
                 "model_configs": [{"purpose": "审核", "model_name": "deepseek-flash"}]},
        "runs": [run(1, "女", 100), run(2, "男", 300), run(3, "女", 500)],
    }


MATERIAL_BUILDERS = {
    "quality_pairwise.py": "build_materials",
    "content_faithfulness.py": "build_judge_materials",
    "false_reject.py": "build_judge_materials",
}


def _builder_guard_issues(sources: dict[str, str]) -> list[str]:
    """材料构造函数必须在返回前调用 assert_safe_material（静态查函数体，防“只定义不调用”）。"""
    issues: list[str] = []
    for name, builder in MATERIAL_BUILDERS.items():
        text = sources.get(name)
        if text is None:
            continue
        marker = f"def {builder}("
        start = text.find(marker)
        if start < 0:
            issues.append(f"{name} 缺少 {builder}，judge 材料构造不可验证")
            continue
        rest = text[start + len(marker):]
        end = rest.find("\ndef ")
        body = rest if end < 0 else rest[:end]
        if "assert_safe_material" not in body:
            issues.append(f"{name}.{builder} 未在返回前调用 assert_safe_material（泄漏不 fail-closed）")
    return issues


def _guard_probe(label: str, guard, cleaner=None) -> list[str]:
    """闸门探针：assert_safe_material 必须拦截禁字段；safe_person 必须剥禁字段。"""
    issues: list[str] = []
    dirty = {"candidate": {"delivered_rank": 1, "screen_score": 99, "evidence": ["同门店"]}}
    if not callable(guard):
        issues.append(f"{label} 缺少 assert_safe_material 闸门")
    else:
        try:
            guard(dirty)
        except ValueError:
            pass
        except Exception as exc:  # noqa: BLE001
            issues.append(f"{label}.assert_safe_material 异常类型不对：{type(exc).__name__}: {exc}")
        else:
            issues.append(f"{label}.assert_safe_material 未拦截禁字段")
    if cleaner is not None:
        if not callable(cleaner):
            issues.append(f"{label} 缺少 safe_person 清洗函数")
        else:
            try:
                clean = cleaner({"delivered_rank": 1, "screen_score": 99,
                                 "evidence": ["同门店"], "gender": "女"}) or {}
                leaked = sorted(str(key) for key in clean
                                if str(key) in FORBIDDEN_MATERIAL_KEYS
                                or str(key).endswith("_role"))
                if leaked:
                    issues.append(f"{label}.safe_person 泄漏禁字段 {leaked}")
            except Exception as exc:  # noqa: BLE001
                issues.append(f"{label}.safe_person 探针异常：{type(exc).__name__}: {exc}")
    return issues


def _probe_content_materials(module) -> list[str]:
    """content_faithfulness：build_items -> build_judge_materials，材料必须只含白名单字段。"""
    build_items = getattr(module, "build_items", None)
    build_materials = getattr(module, "build_judge_materials", None)
    if not (callable(build_items) and callable(build_materials)):
        return ["content_faithfulness 缺少 build_items/build_judge_materials，材料白名单无法动态验证"]
    try:
        items = build_items(_synthetic_quality_bundle(), limit_items=6)
        materials = build_materials(items)
    except Exception as exc:  # noqa: BLE001
        return [f"content_faithfulness 材料构造异常：{type(exc).__name__}: {exc}"]
    issues: list[str] = []
    if not materials:
        issues.append("content_faithfulness 未构造出任何 judge 材料")
    expected = {"item_id", "kind", "content", "source_text"}
    for material in materials:
        extra = set(material) - expected
        missing = expected - set(material)
        if extra:
            issues.append(f"content 材料出现非白名单字段 {sorted(extra)}")
        if missing:
            issues.append(f"content 材料缺少字段 {sorted(missing)}")
    guard = getattr(module, "assert_safe_material", None)
    if callable(guard):
        try:
            guard(materials)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"content 材料被自家闸门拦截：{type(exc).__name__}: {exc}")
    try:
        assert_safe_material(materials)
    except ValueError as exc:
        issues.append(f"content 材料被 pairwise 闸门拦截：{exc}")
    return issues


def _probe_false_reject_materials(module) -> list[str]:
    """false_reject：replay -> build_judge_materials；reject_code/reject_reason 是允许的被评对象。"""
    replay = getattr(module, "replay", None)
    build_materials = getattr(module, "build_judge_materials", None)
    if not (callable(replay) and callable(build_materials)):
        return ["false_reject 缺少 replay/build_judge_materials，材料白名单无法动态验证"]
    try:
        replayed = replay(_synthetic_quality_bundle())
    except Exception as exc:  # noqa: BLE001
        return [f"false_reject replay 异常：{type(exc).__name__}: {exc}"]
    soft_codes = {"PREFERENCE_CONFLICT", "PORTRAIT_INSUFFICIENT"}
    rows = [row for row in (replayed.get("rejected") or [])
            if str(row.get("code")) in soft_codes]
    if not rows:
        return ["false_reject 在合成 bundle 上未产出软冲突样本，材料白名单无法验证"]
    try:
        materials = build_materials(rows)
    except Exception as exc:  # noqa: BLE001
        return [f"false_reject 材料构造异常：{type(exc).__name__}: {exc}"]
    issues: list[str] = []
    allowed = {"item_id", "kind", "reject_code", "reject_reason",
               "applicant", "applicant_preference",
               "candidate", "candidate_preference"}
    for material in materials:
        extra = set(material) - allowed
        if extra:
            issues.append(f"false_reject 材料出现非白名单字段 {sorted(extra)}")
    dumped = json.dumps(materials, ensure_ascii=False)
    for leaked in ("delivered_rank", "screen_score", "audit_status", "candidate_row_id"):
        if leaked in dumped:
            issues.append(f"false_reject 材料字符串出现 {leaked}")
    guard = getattr(module, "assert_safe_material", None)
    if callable(guard):
        try:
            guard(materials)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"false_reject 材料被自家闸门拦截：{type(exc).__name__}: {exc}")
    return issues


def _dynamic_material_issues() -> list[str]:
    """动态探针：真实调用新模块的材料构造，断言 emit 材料过白名单（不只看源码）。"""
    issues: list[str] = []

    # 1) quality_pairwise：build -> build_materials，整包材料必须过 pairwise_quality 闸门
    if (ROOT / "quality_pairwise.py").is_file():
        try:
            module = importlib.import_module("quality_pairwise")
            build = getattr(module, "build", None)
            build_materials = getattr(module, "build_materials", None)
            if not (callable(build) and callable(build_materials)):
                issues.append("quality_pairwise 缺少 build/build_materials，材料白名单无法动态验证")
            else:
                pairs = build(_synthetic_quality_bundle(), limit_pairs=6)
                if not pairs:
                    issues.append("quality_pairwise.build 未产出 pair（合成 bundle 不兼容）")
                else:
                    materials = build_materials(pairs)
                    try:
                        assert_safe_material(materials)
                    except ValueError as exc:
                        issues.append(f"quality_pairwise 材料泄漏禁字段：{exc}")
                    dumped = json.dumps(materials, ensure_ascii=False)
                    for leaked in ("delivered_rank", "screen_score", '"evidence"', "A_role"):
                        if leaked in dumped:
                            issues.append(f"quality_pairwise 材料字符串出现 {leaked}")
        except Exception as exc:  # noqa: BLE001 - 探针失败即 fail-closed
            issues.append(f"quality_pairwise 材料探针异常：{type(exc).__name__}: {exc}")

    # 2) content_faithfulness：build_items -> build_judge_materials -> 自家/统一闸门
    if (ROOT / "content_faithfulness.py").is_file():
        try:
            module = importlib.import_module("content_faithfulness")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"content_faithfulness import 失败：{type(exc).__name__}: {exc}")
        else:
            issues += _guard_probe("content_faithfulness",
                                   getattr(module, "assert_safe_material", None))
            issues += _probe_content_materials(module)

    # 3) false_reject：replay -> build_judge_materials -> 自家闸门（允许 reject_code/reject_reason）
    if (ROOT / "false_reject.py").is_file():
        try:
            module = importlib.import_module("false_reject")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"false_reject import 失败：{type(exc).__name__}: {exc}")
        else:
            issues += _guard_probe("false_reject",
                                   getattr(module, "assert_safe_material", None),
                                   getattr(module, "safe_person", None))
            issues += _probe_false_reject_materials(module)
    return issues



def _quality_claim_payloads() -> dict:
    """6 指标“齐全且达线”的合成 payload（positive control，用于证明门禁不是永远 blocked）。"""
    return {
        "match_quality": {"win_rate": 0.66, "win_rate_ci95": {"lo": 0.56, "hi": 0.75},
                          "n_pairs": 120, "n_pairs_judged": 120},
        "false_reject": {"hard": {"rate": 0.0, "n": 120},
                         "soft": {"n": 60, "rate": 0.05},
                         "false_pass": {"count": 0}},
        "delivery_recall": {"mean_attainment": 0.96, "mean_precision": 1.0, "n_scenarios": 8},
        "content_faithfulness": {"faithful_rate": 0.96, "contradiction_rate": 0.01,
                                 "evidence_coverage": 1.0, "n_claims": 240},
        "pass_k": {"k": 3, "n_scenarios": 10, "n_trials": 3, "pass_k": 0.90},
        "safety": {"hard_rule_violations": 0,
                   "negative_assertions": {"total": 3, "passed": 3},
                   "injection": {"attempts": 20, "success_rate": 0.0}},
    }


def _clean_calibration(**overrides) -> dict:
    """干净校准：按指标返回映射（quality-v1 每个语义指标各有一份校准）。"""
    base = {"usable": True, "human": {"kappa": 0.72, "n": 40},
            "position_consistency": 0.92, "reasons": []}
    base.update(overrides)
    return {metric: {**base, "metric": metric}
            for metric in ("match_quality", "false_reject", "content_faithfulness")}


def _claim_gate_probe_failures(spec) -> list[str]:
    """claim_gate fail-closed 探针：缺校准/κ低/位置一致性低/仪器不可用/样本不足必须 blocked。

    只用 spec 的公开接口（evaluate_claims），因此可以用“永远放行”的假 spec 反向测试本探针。
    """
    payloads = _quality_claim_payloads()
    evaluate = getattr(spec, "evaluate_claims", None)
    if not callable(evaluate):
        return ["quality_spec 缺少 evaluate_claims，无法验证 claim 门禁"]
    failures: list[str] = []

    def expect_blocked(label: str, calibration, metric_payloads=None, must_mention: str | None = None):
        result = evaluate(metric_payloads if metric_payloads is not None else payloads, calibration)
        if not isinstance(result, dict):
            failures.append(f"{label}：evaluate_claims 未返回 dict")
            return
        if result.get("quality_claim_allowed"):
            failures.append(f"{label}：quality_claim_allowed 应为 False，实际 True（门禁被绕过）")
        elif must_mention:
            joined = "；".join(str(reason) for reason in (result.get("reasons") or []))
            if must_mention not in joined:
                failures.append(f"{label}：blocked 但 reasons 未点明原因（缺 {must_mention!r}）：{joined[:160]}")

    healthy = evaluate(payloads, _clean_calibration())
    if not isinstance(healthy, dict) or not healthy.get("quality_claim_allowed"):
        failures.append("齐全达线时 quality_claim_allowed 应为 True，实际 "
                        f"{healthy.get('quality_claim_allowed') if isinstance(healthy, dict) else healthy}")
    # 1) 缺人工校准报告（judge 不能当质量真值）
    expect_blocked("缺人工校准", None, must_mention="人工校准")
    # 2) 人工一致性 kappa 低于 0.6
    expect_blocked("kappa=0.4", _clean_calibration(human={"kappa": 0.4, "n": 40}), must_mention="kappa")
    # 3) 位置一致性低于 0.85（位置偏差）
    expect_blocked("position_consistency=0.5", _clean_calibration(position_consistency=0.5),
                   must_mention="位置")
    # 4) judge 仪器校验未通过
    expect_blocked("仪器不可用", _clean_calibration(usable=False), must_mention="仪器")
    # 5) 样本量不足：配对/软冲突/claim
    insufficient = copy.deepcopy(payloads)
    insufficient["match_quality"]["n_pairs"] = 12
    expect_blocked("pairwise 样本不足", _clean_calibration(), insufficient, must_mention="样本")
    insufficient = copy.deepcopy(payloads)
    insufficient["false_reject"]["soft"]["n"] = 5
    expect_blocked("软冲突样本不足", _clean_calibration(), insufficient, must_mention="软冲突")
    insufficient = copy.deepcopy(payloads)
    insufficient["content_faithfulness"]["n_claims"] = 20
    expect_blocked("content claims 不足", _clean_calibration(), insufficient, must_mention="claim")
    # 6) 缺测量 artifact
    missing = copy.deepcopy(payloads)
    missing["match_quality"] = None
    expect_blocked("缺 artifact", _clean_calibration(), missing, must_mention="artifact")
    return failures


@_check("质量阈值未放松")
def check_quality_thresholds():
    drift = _quality_spec_drift(quality_spec)
    _assert(not drift, f"quality_spec 对外口径被改动（未同步冻结基线）：{drift[:6]}")
    return (f"protocol/judge 版本、JUDGE_GATES({len(quality_spec.JUDGE_GATES)})、"
            f"SAMPLE_FLOORS({len(quality_spec.SAMPLE_FLOORS)})、6 指标 thresholds 与冻结基线一致")


@_check("新质量模块无场景硬编码")
def check_quality_no_hardcode():
    paths = {name: ROOT / name for name in QUALITY_MODULES}
    existing = {name: path.read_text(encoding="utf-8", errors="replace")
                for name, path in paths.items() if path.is_file()}
    hits = _scan_quality_hardcode(existing)
    _assert(not hits, f"新质量模块出现场景硬编码：{hits[:8]}")
    missing = sorted(name for name, path in paths.items() if not path.is_file())
    if not existing:
        return "质量模块尚未落盘，跳过场景硬编码扫描"
    detail = f"{len(existing)} 个质量模块无 V3_/V4_ 硬编码"
    if missing:
        detail += f"（尚未落盘：{missing}）"
    return detail


@_check("新模块 judge 材料白名单")
def check_quality_material():
    sources = {}
    for name in QUALITY_MODULES:
        path = ROOT / name
        if path.is_file():
            sources[name] = path.read_text(encoding="utf-8", errors="replace")
    issues = _material_guard_issues(sources)
    issues += _builder_guard_issues(sources)
    issues += _dynamic_material_issues()
    _assert(not issues, issues)
    # 动态兜底：材料闸门本身仍能拦截禁字段（防止被改成宽松阀）
    try:
        assert_safe_material({"pairs": [{"A": {"delivered_rank": 1}}]})
    except ValueError:
        pass
    else:
        raise AssertionError("assert_safe_material 未拦截 delivered_rank")
    if not sources:
        return "质量模块尚未落盘，跳过材料白名单探针"
    return f"{len(sources)} 个质量模块均复用 safe_person/assert_safe_material 闸门（含动态材料探针）"


@_check("质量门禁 fail-closed 探针")
def check_quality_claim_gate():
    failures = _claim_gate_probe_failures(quality_spec)
    _assert(not failures, failures)
    return "缺校准/κ<0.6/位置一致性低/仪器不可用/样本不足/缺 artifact 均 blocked；齐全达线才 allowed"


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