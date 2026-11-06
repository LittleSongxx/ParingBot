"""端到端离线集成测试：pairwise judge -> 人工校准 -> 质量报告 claims 门禁。

三条链路（全部 mock/注入 judge，不打网络、不连 DB）：
1. 合成 bundle -> eval/quality_pairwise.build/run（fake verdicts / 注入 judge_fn）
   -> match_quality JSON：schema、分层、材料白名单、Wilson CI、position consistency、usable 门禁；
2. 合成 pairwise judge 输出 + 完美/含噪人工标签 -> judge_calibration.calibrate
   -> judge-human kappa / PPI / usable 门禁；
3. 合成 6 指标 payload -> quality_report.build -> claims 门禁
   （缺人工校准 / kappa 低 / 样本不足必须 quality_claim_allowed=False；齐全达线才 True）。

quality_pairwise.py 由队友并行实现；未落盘时相关用例 skip（其余链路照跑）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import judge_calibration as jc  # noqa: E402
import quality_report as qr  # noqa: E402
import quality_spec as spec  # noqa: E402
from lib import stats  # noqa: E402

PAIRWISE_PATH = EVAL / "quality_pairwise.py"
HAS_PAIRWISE = PAIRWISE_PATH.is_file()

REPO = EVAL.parent


def synthetic_bundle() -> dict:
    """3 run 的最小合法 bundle：delivered / near_miss / rejected 三档都有。"""
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
        return {
            "run": {"id": run_id, "run_no": f"QUALITY-PIPELINE-{run_id}",
                    "status": "已完成", "total_round": 3,
                    "prompt_tokens": 100, "completion_tokens": 10, "summary": "pipeline"},
            "task": {"id": run_id, "deliver_count": 2, "total_round": 3},
            "applicant": person(base_id, gender),
            "deliverable_passed_count": 4, "delivered_to_user": 2, "truncated_count": 0,
            "candidates": [
                candidate(base_id + 1, gender, delivered=True),
                candidate(base_id + 2, gender, delivered=True),
                candidate(base_id + 3, gender, passed=True),
                candidate(base_id + 4, gender, passed=True),
                candidate(base_id + 5, gender, audit_status="否决",
                          reject_code="MISMATCH_HARD", reject_reason="硬条件不匹配"),
                candidate(base_id + 6, gender, audit_status="否决",
                          reject_code="PREFERENCE_CONFLICT", reject_reason="偏好冲突"),
            ],
            "rounds": [], "funnel": {"stages": []},
        }

    return {
        "generated_at": "2026-11-06 00:00:00",
        "meta": {"code_commit": "pipeline-test", "scenario_suite": "v3",
                 "db_profile": "eval",
                 "model_configs": [{"purpose": "审核", "model_name": "deepseek-flash"}]},
        "runs": [run(1, "女", 100), run(2, "男", 300), run(3, "女", 500)],
    }


def _swap(side: str) -> str:
    return "B" if side == "A" else "A"


def fake_verdicts(pairs: list[dict], strategy: str = "delivered") -> list[dict]:
    """按 pair 的 delivered_side 构造双向 verdict。

    - delivered：forward 选 delivered（A=delivered），backward 选交换后的 delivered（位置一致）；
    - position_bias：backward 固定选 delivered_side，制造方向不一致；
    - forward_only：只给 forward，backward 缺失（judge-core 契约：记 error，不自动镜像）。
    """
    verdicts: list[dict] = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        side = pair["delivered_side"]
        if strategy == "delivered":
            verdicts.append({"pair_id": pair_id, "direction": "forward", "winner": side})
            verdicts.append({"pair_id": pair_id, "direction": "backward", "winner": _swap(side)})
        elif strategy == "position_bias":
            verdicts.append({"pair_id": pair_id, "direction": "forward", "winner": "A"})
            verdicts.append({"pair_id": pair_id, "direction": "backward", "winner": side})
        elif strategy == "forward_only":
            verdicts.append({"pair_id": pair_id, "direction": "forward", "winner": side})
        else:  # pragma: no cover - 防御
            raise ValueError(strategy)
    return verdicts


# ---------------------------------------------------------------------------
# 1) pairwise 链路
# ---------------------------------------------------------------------------


@unittest.skipUnless(HAS_PAIRWISE, "quality_pairwise.py 尚未落盘（队友 task-5 实现中）")
class PairwisePipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import quality_pairwise as qp

        cls.qp = qp
        cls.bundle = synthetic_bundle()
        cls.pairs = qp.build(cls.bundle, limit_pairs=9, seed=20261106)

    def test_build_strata_and_roles(self):
        self.assertTrue(self.pairs, "合成 bundle 应能产出 pair")
        strata = {pair["stratum"] for pair in self.pairs}
        self.assertTrue(strata <= {"near_miss", "rejected", "random"}, strata)
        self.assertTrue(strata, "至少要有一种分层")
        ids = [pair["pair_id"] for pair in self.pairs]
        self.assertEqual(len(ids), len(set(ids)), "pair_id 必须唯一")
        for pair in self.pairs:
            self.assertIn(pair["delivered_side"], ("A", "B"))
            self.assertIn("applicant", pair)

    def test_build_materials_are_whitelisted(self):
        import pairwise_quality

        materials = self.qp.build_materials(self.pairs)
        self.assertEqual(set(materials) & {"protocol", "pairs", "key"},
                         {"protocol", "pairs", "key"})
        self.assertEqual(len(materials["pairs"]), len(self.pairs))
        for item in materials["pairs"]:
            self.assertEqual(set(item),
                             {"pair_id", "stratum", "applicant", "candidate_a", "candidate_b"})
        for pair_id, meta in materials["key"].items():
            self.assertEqual(set(meta),
                             {"delivered_side", "delivered_id", "control_id", "stratum"})
            self.assertIn(meta["delivered_side"], ("A", "B"))
        pairwise_quality.assert_safe_material(materials)  # 泄漏禁字段会 raise
        dumped = json.dumps(materials, ensure_ascii=False)
        for needle in ("delivered_rank", "screen_score", '"evidence"', '"A_role"',
                       '"audit_status"', '"passed"'):
            self.assertNotIn(needle, dumped, f"judge 材料泄漏 {needle}")

    def test_run_fake_verdicts_schema_and_statistics(self):
        payload = self.qp.run(self.bundle, fake_verdicts=fake_verdicts(self.pairs, "delivered"),
                              models=("qwen3.7-plus",), limit_pairs=9, seed=20261106)
        self.assertEqual(payload["metric"], "match_quality")
        self.assertEqual(payload["protocol"], spec.PROTOCOL_VERSION)
        self.assertEqual(payload["judge_version"], spec.JUDGE_VERSION)
        for key in ("n_pairs", "n_pairs_judged", "n_errors", "delivered_wins",
                    "control_wins", "ties", "inconsistent", "win_rate",
                    "win_rate_ci95", "position_consistency",
                    "position_consistency_ci95", "by_stratum", "by_judge",
                    "bradley_terry", "pairs", "materials_safe", "usable", "reasons"):
            self.assertIn(key, payload, key)
        self.assertEqual(payload["n_pairs"], len(self.pairs))
        self.assertEqual(payload["n_errors"], 0)
        self.assertEqual(payload["win_rate"], 1.0)                     # fake judge 100% 选交付
        self.assertEqual(payload["position_consistency"], 1.0)         # 双向一致
        self.assertGreaterEqual(payload["delivered_wins"], 1)
        self.assertTrue(payload["materials_safe"])
        self.assertTrue(payload["usable"], payload["reasons"])
        ci = payload["win_rate_ci95"]
        self.assertLessEqual(0.0, ci["lo"])
        self.assertLessEqual(ci["lo"], ci["hi"])
        self.assertLessEqual(ci["hi"], 1.0)
        self.assertEqual(ci["n"], payload["n_pairs_judged"])
        # Wilson/CP 区间在 n 有限时下限应严格小于点估计
        self.assertLess(ci["lo"], 1.0)
        # 分层统计：每个出现的 stratum 都要有样本数与胜率（字段名是 n_pairs）
        for stratum, block in payload["by_stratum"].items():
            self.assertIn("n_pairs", block, stratum)
            self.assertIn("win_rate", block, stratum)
            self.assertEqual(block["n_pairs"], block.get("n_pairs_judged"), stratum)
        # BT 强度中，交付候选整体应更强（若 BT 给出条目）
        strengths = (payload.get("bradley_terry") or {}).get("strengths") or {}
        if strengths:
            self.assertTrue(all(value >= 0 for value in strengths.values()))

    def test_position_bias_marks_unusable(self):
        payload = self.qp.run(self.bundle,
                              fake_verdicts=fake_verdicts(self.pairs, "position_bias"),
                              models=("qwen3.7-plus",), limit_pairs=9, seed=20261106)
        self.assertLess(payload["position_consistency"], 0.85, payload["position_consistency"])
        self.assertFalse(payload["usable"])
        self.assertTrue(any("position" in reason.lower() or "位置" in reason
                            for reason in payload["reasons"]), payload["reasons"])

    def test_missing_backward_counts_as_error(self):
        payload = self.qp.run(self.bundle,
                              fake_verdicts=fake_verdicts(self.pairs, "forward_only"),
                              models=("qwen3.7-plus",), limit_pairs=9, seed=20261106)
        self.assertGreater(payload["n_errors"], 0)
        self.assertGreater(payload["n_errors"] / max(1, payload["n_pairs"]), 0.20)
        self.assertFalse(payload["usable"])

    def test_injected_judge_fn_offline(self):
        calls: list[str] = []

        def fake_judge(prompt, model, env):
            calls.append(model)
            return {"winner": "tie", "reason": "fake"}

        payload = self.qp.run(self.bundle, judge_fn=fake_judge,
                              models=("fake-judge",), limit_pairs=9, seed=20261106)
        self.assertTrue(calls, "judge_fn 必须被调用")
        self.assertEqual(payload["n_errors"], 0)
        self.assertEqual(payload["ties"], payload["n_pairs_judged"])
        self.assertEqual(payload["win_rate"], 0.5)       # tie 记 0.5
        self.assertEqual(payload["position_consistency"], 1.0)
        self.assertTrue(payload["usable"])

    def test_run_output_feeds_calibration(self):
        payload = self.qp.run(self.bundle, fake_verdicts=fake_verdicts(self.pairs, "delivered"),
                              models=("qwen3.7-plus",), limit_pairs=9, seed=20261106)
        # fake judge 永远判 delivered（fake_verdicts 已按 delivered_side 归一）；
        # 完美人工标签也全判 delivered -> judge-human kappa=1.0
        human = {pair["pair_id"]: "delivered" for pair in self.pairs}
        calibration = jc.calibrate(payload, human, metric="match_quality",
                                   human_agreement={"n": 30, "kappa": 0.8})
        self.assertEqual(calibration["metric"], "match_quality")
        self.assertEqual(calibration["judge_human"]["n"], len(payload["pairs"]),
                         "pairwise 输出需能映射回 delivered/control/tie")
        self.assertEqual(calibration["judge_human"]["kappa"], 1.0)
        # 合成 bundle 只有 9 对 < 50：calibrate 必须按小样本 fail-closed，而不是给 usable
        self.assertFalse(calibration["usable"])
        self.assertTrue(any("50" in reason or "样本" in reason
                            for reason in calibration["reasons"]), calibration["reasons"])
        self.assertTrue(calibration["ppi"]["available"])
        # 小样本校准不能支撑质量结论
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "pipeline-test"})
        self.assertIn("claims", report)
        self.assertFalse(report["claims"]["quality_claim_allowed"])


# ---------------------------------------------------------------------------
# 2) 人工校准链路
# ---------------------------------------------------------------------------


def _pair_row(pair_id: str, outcome: str, stratum: str = "near_miss") -> dict:
    row = {"pair_id": pair_id, "stratum": stratum,
           "delivered_win": outcome == "delivered",
           "control_win": outcome == "control",
           "tie": outcome == "tie"}
    return row


def _pairwise_judge_payload(outcomes: list[str], position: float = 0.95) -> dict:
    pairs = [_pair_row(f"p{i}", outcome) for i, outcome in enumerate(outcomes)]
    return {"metric": "match_quality", "protocol": spec.PROTOCOL_VERSION,
            "judge_version": spec.JUDGE_VERSION, "n_pairs": len(pairs),
            "n_pairs_judged": len(pairs), "position_consistency": position,
            "pairs": pairs, "by_judge": {}}


def _anchors_file(tmp: Path) -> str:
    path = tmp / "anchors.json"
    path.write_text(json.dumps({"items": [
        {"item_id": "b1", "kind": "bad", "judge": 2.0},
        {"item_id": "b2", "kind": "bad", "judge": 2.2},
        {"item_id": "c1", "kind": "clean", "judge": 4.8},
        {"item_id": "c2", "kind": "clean", "judge": 4.9},
    ]}), encoding="utf-8")
    return str(path)


def _metric_payloads() -> dict:
    """6 指标全部达线的合成 payload（positive control）。"""
    return {
        "match_quality": {
            "metric": "match_quality", "n_pairs": 120, "n_pairs_judged": 115,
            "win_rate": 0.72,
            "win_rate_ci95": {"mean": 0.72, "lo": 0.63, "hi": 0.80, "n": 115,
                              "method": "wilson"},
            "position_consistency": 0.92,
            "by_stratum": {"near_miss": {"n": 60, "win_rate": 0.70},
                           "rejected": {"n": 30, "win_rate": 0.80},
                           "random": {"n": 30, "win_rate": 0.90}},
        },
        "false_reject": {
            "metric": "false_reject",
            "hard": {"n": 120, "false_reject": 0, "rate": 0.0,
                     "ci95": {"mean": 0.0, "lo": 0.0, "hi": 0.03, "n": 120}},
            "soft": {"n": 60, "false_reject": 2, "rate": 0.033,
                     "ci95": {"mean": 0.033, "lo": 0.004, "hi": 0.115, "n": 60}},
            "false_pass": {"n": 100, "count": 0, "rate": 0.0},
        },
        "delivery_recall": {
            "metric": "delivery_recall", "n_scenarios": 8,
            "mean_attainment": 0.99, "mean_precision": 1.0,
            "attainment_ci95": {"mean": 0.99, "lo": 0.95, "hi": 1.0, "n": 8},
        },
        "content_faithfulness": {
            "metric": "content_faithfulness", "n_items": 50, "n_claims": 300,
            "faithful_rate": 0.97,
            "faithful_ci95": {"mean": 0.97, "lo": 0.945, "hi": 0.985, "n": 300},
            "contradiction_rate": 0.01, "evidence_coverage": 1.0,
        },
        "pass_k": {
            "metric": "pass_k", "k": 3, "pass_k": 0.94, "pass_1": 0.98,
            "n_scenarios": 12, "n_trials": 3,
            "pass_k_ci95": {"mean": 0.94, "lo": 0.86, "hi": 0.99, "n": 12},
        },
        "safety": {
            "metric": "safety", "hard_rule_violations": 0,
            "negative_assertions": {"passed": 2, "total": 2},
            "injection": {"attempts": 24, "successes": 0, "success_rate": 0.0},
        },
    }

def _calibrations(base: dict, metrics=("match_quality", "content_faithfulness", "false_reject")) -> dict:
    """quality-v1 每个语义指标各有一份人工校准；这里把单份校准扩成映射便于构造测试。"""
    return {metric: {**base, "metric": metric} for metric in metrics}
class JudgeCalibrationPipelineTest(unittest.TestCase):
    def test_perfect_labels_make_instrument_usable(self):
        outcomes = ["delivered" if i % 2 == 0 else "control" for i in range(60)]
        human = {f"p{i}": outcome for i, outcome in enumerate(outcomes)}
        with tempfile.TemporaryDirectory() as tmp:
            anchors = _anchors_file(Path(tmp))
            calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                       metric="match_quality",
                                       human_agreement={"n": 60, "kappa": 0.8},
                                       anchors_path=anchors)
        self.assertTrue(calibration["usable"], calibration["reasons"])
        self.assertEqual(calibration["judge_human"]["kappa"], 1.0)
        self.assertEqual(calibration["n_labeled"], 60)
        self.assertTrue(calibration["ppi"]["available"])
        self.assertTrue(calibration["anchors"]["passed"])
        # 校准结果可直接喂给报告：仪器通过 + 6 指标达线 => 允许申报
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "pipeline-test"})
        self.assertTrue(report["claims"]["quality_claim_allowed"], report["claims"]["reasons"])

    def test_noisy_labels_block_claim(self):
        # judge 全判 delivered；人工一半 control -> kappa 低，仪器不可用
        outcomes = ["delivered"] * 60
        human = {f"p{i}": ("delivered" if i % 2 == 0 else "control") for i in range(60)}
        calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                   metric="match_quality",
                                   human_agreement={"n": 60, "kappa": 0.8})
        self.assertFalse(calibration["usable"])
        self.assertTrue(any("kappa" in reason for reason in calibration["reasons"]))
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "pipeline-test"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])
        blocked = report["claims"]["per_metric"]["match_quality"]
        self.assertFalse(blocked["allowed"])
        self.assertTrue(blocked["reasons"])

    def test_ppi_corrects_judge_optimism(self):
        # judge 全判 delivered；人工子集 20 个里 15 delivered -> 校正后 < 原始 1.0
        outcomes = ["delivered"] * 60
        human = {f"p{i}": ("delivered" if i < 15 else "control") for i in range(20)}
        calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                   metric="match_quality",
                                   human_agreement={"n": 60, "kappa": 0.8})
        ppi = calibration["ppi"]
        self.assertTrue(ppi["available"])
        self.assertGreater(ppi["raw_judge_rate"], 0.99)
        self.assertLess(ppi["corrected_rate"], 0.85)
        self.assertLessEqual(ppi["lo"], ppi["corrected_rate"])
        self.assertLessEqual(ppi["corrected_rate"], ppi["hi"])

    def test_position_bias_blocks(self):
        outcomes = ["delivered"] * 60
        human = {f"p{i}": "delivered" for i in range(60)}
        calibration = jc.calibrate(_pairwise_judge_payload(outcomes, position=0.60), human,
                                   metric="match_quality",
                                   human_agreement={"n": 60, "kappa": 0.8})
        self.assertFalse(calibration["usable"])
        self.assertTrue(any("position" in reason.lower() or "位置" in reason
                            for reason in calibration["reasons"]))

    def test_missing_annotator_agreement_blocks(self):
        outcomes = ["delivered"] * 60
        human = {f"p{i}": "delivered" for i in range(60)}
        calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                   metric="match_quality")
        self.assertFalse(calibration["usable"])
        self.assertTrue(any("双人" in reason or "kappa" in reason
                            for reason in calibration["reasons"]))

    def test_anchor_failure_blocks(self):
        outcomes = ["delivered"] * 60
        human = {f"p{i}": "delivered" for i in range(60)}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anchors.json"
            path.write_text(json.dumps({"items": [
                {"item_id": "b1", "kind": "bad", "judge": 4.9},
                {"item_id": "c1", "kind": "clean", "judge": 4.2},
            ]}), encoding="utf-8")
            calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                       metric="match_quality",
                                       human_agreement={"n": 60, "kappa": 0.8},
                                       anchors_path=str(path))
        self.assertFalse(calibration["usable"])
        self.assertEqual(calibration["anchors"]["passed"], False)

    def test_content_calibration_chain(self):
        claims = [{"claim_id": f"c{i}", "label": "supported"} for i in range(60)]
        payload = {"metric": "content_faithfulness", "n_claims": 60, "claims": claims}
        human = {f"c{i}": "supported" for i in range(60)}
        calibration = jc.calibrate(payload, human, metric="content_faithfulness",
                                   human_agreement={"n": 60, "kappa": 0.75})
        self.assertTrue(calibration["usable"], calibration["reasons"])
        self.assertEqual(calibration["judge_human"]["kappa"], 1.0)
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "pipeline-test"})
        self.assertTrue(report["claims"]["per_metric"]["content_faithfulness"]["allowed"])


# ---------------------------------------------------------------------------
# 3) 质量报告 claims 门禁
# ---------------------------------------------------------------------------


class QualityReportPipelineTest(unittest.TestCase):
    def test_full_payloads_and_usable_calibration_allow_claims(self):
        calibration = {
            "metric": "match_quality", "usable": True,
            "human": {"n": 100, "kappa": 0.72, "agreement": 0.84},
            "judge_human": {"n": 100, "kappa": 0.71, "agreement": 0.86},
            "position_consistency": 0.92, "reasons": [],
            "ppi": {"available": True, "raw_judge_rate": 0.72,
                    "corrected_rate": 0.70, "lo": 0.60, "hi": 0.79},
        }
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "abc123"})
        self.assertTrue(report["claims"]["quality_claim_allowed"],
                        report["claims"]["reasons"])
        self.assertEqual(len(report["rows"]), 6)
        for key in spec.ORDER:
            self.assertTrue(report["claims"]["per_metric"][key]["allowed"], key)
        text = qr.render(report)
        self.assertIn("质量报告", text)
        self.assertIn("匹配质量胜率", text)
        self.assertIn("可申报", text)
        self.assertEqual(text, qr.render(report), "render 必须确定性可复现")

    def test_missing_calibration_blocks_quality_claims(self):
        report = qr.build(_metric_payloads(), None, {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])
        self.assertTrue(report["claims"]["reasons"])
        # 确定性指标（delivery_recall/pass_k/safety）不受人工校准缺失影响
        for key in ("delivery_recall", "pass_k", "safety"):
            self.assertTrue(report["claims"]["per_metric"][key]["allowed"], key)

    def test_unusable_calibration_blocks(self):
        calibration = {"usable": False, "human": {"kappa": 0.72},
                       "position_consistency": 0.92,
                       "reasons": ["judge-human kappa=0.4 < 0.6"]}
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])

    def test_low_kappa_calibration_blocks(self):
        calibration = {"usable": True, "human": {"kappa": 0.40},
                       "position_consistency": 0.92, "reasons": []}
        report = qr.build(_metric_payloads(), _calibrations(calibration), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])

    def test_insufficient_pairwise_sample_blocks(self):
        payloads = _metric_payloads()
        payloads["match_quality"]["n_pairs"] = 40
        payloads["match_quality"]["n_pairs_judged"] = 40
        calibration = {"usable": True, "human": {"kappa": 0.72},
                       "position_consistency": 0.92, "reasons": []}
        report = qr.build(payloads, _calibrations(calibration), {"code_commit": "abc123"})
        gate = report["claims"]["per_metric"]["match_quality"]
        self.assertFalse(gate["allowed"])
        self.assertTrue(any("样本" in reason for reason in gate["reasons"]), gate["reasons"])
        self.assertFalse(report["claims"]["quality_claim_allowed"])

    def test_missing_metric_reported_not_crashing(self):
        payloads = _metric_payloads()
        payloads.pop("safety")
        calibration = {"usable": True, "human": {"kappa": 0.72},
                       "position_consistency": 0.92, "reasons": []}
        report = qr.build(payloads, _calibrations(calibration), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["per_metric"]["safety"]["allowed"])
        self.assertEqual(len(report["rows"]), 6)

    def test_cli_roundtrip_with_calibration_file(self):
        outcomes = ["delivered" if i % 2 == 0 else "control" for i in range(60)]
        human = {f"p{i}": outcome for i, outcome in enumerate(outcomes)}
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            anchors = _anchors_file(tmp)
            calibration = jc.calibrate(_pairwise_judge_payload(outcomes), human,
                                       metric="match_quality",
                                       human_agreement={"n": 60, "kappa": 0.8},
                                       anchors_path=anchors)
            self.assertTrue(calibration["usable"])
            calibration_path = tmp / "calibration.json"
            calibration_path.write_text(json.dumps(_calibrations(calibration), ensure_ascii=False),
                                        encoding="utf-8")
            payloads = _metric_payloads()
            paths = {}
            for key, payload in payloads.items():
                path = tmp / f"{key}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                paths[key] = path
            report_json = tmp / "report.json"
            report_md = tmp / "report.md"
            code = qr.main([
                "--pairwise", str(paths["match_quality"]),
                "--false-reject", str(paths["false_reject"]),
                "--recall", str(paths["delivery_recall"]),
                "--content", str(paths["content_faithfulness"]),
                "--pass-k", str(paths["pass_k"]),
                "--safety", str(paths["safety"]),
                "--calibration", str(calibration_path),
                "--out-md", str(report_md),
                "--out-json", str(report_json),
                "--code-commit", "abc123",
            ])
            self.assertEqual(code, 0)
            data = json.loads(report_json.read_text(encoding="utf-8"))
            self.assertTrue(data["claims"]["quality_claim_allowed"],
                            data["claims"]["reasons"])
            self.assertTrue(report_md.exists())
            # CI 门禁依赖的统计库小样本区间也要可用（Wilson/CP 都是 n>0 时有限）
            ci = stats.wilson_ci(72, 100)
            self.assertLess(ci["lo"], ci["mean"])
            cp = stats.clopper_pearson_ci(0, 120)
            self.assertEqual(cp["lo"], 0.0)


if __name__ == "__main__":
    unittest.main()
