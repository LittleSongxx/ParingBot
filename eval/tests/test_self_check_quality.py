"""self_check 质量门禁加固项的正反两向测试（test the test 的 test）。

覆盖新增 4 项检查的“通过必须 PASS、故意放松必须 FAIL”：
- 质量阈值未放松：quality_spec 与冻结基线一致；任意阈值/门禁/口径被放松都能被 detect；
- 新质量模块无场景硬编码：去注释后扫 V3_/V4_；干净源码不误报；
- 新模块 judge 材料白名单：必须复用 safe_person/assert_safe_material 闸门；
- 质量门禁 fail-closed 探针：真实 quality_spec 全部 blocked 场景成立；
  用“永远放行”的假 spec 反向验证探针本身能识别门禁被绕过。

全部离线（import self_check 会执行它自己那套离线自检，约 1.4s，无 DB/网络）。
"""
from __future__ import annotations

import copy
import sys
import types
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import quality_spec  # noqa: E402
import self_check  # noqa: E402

NEW_CHECK_NAMES = ("质量阈值未放松", "新质量模块无场景硬编码",
                   "新模块 judge 材料白名单", "质量门禁 fail-closed 探针")


def _fake_spec(**overrides):
    """用真实 quality_spec 的当前值构造可改写的假 spec（用于反向测试）。"""
    metrics = {key: types.SimpleNamespace(
        thresholds=copy.deepcopy(quality_spec.METRICS[key].thresholds),
        human_calibration=quality_spec.METRICS[key].human_calibration)
        for key in quality_spec.ORDER}
    spec = types.SimpleNamespace(
        PROTOCOL_VERSION=quality_spec.PROTOCOL_VERSION,
        JUDGE_VERSION=quality_spec.JUDGE_VERSION,
        ORDER=list(quality_spec.ORDER),
        JUDGE_GATES=copy.deepcopy(quality_spec.JUDGE_GATES),
        SAMPLE_FLOORS=copy.deepcopy(quality_spec.SAMPLE_FLOORS),
        METRICS=metrics,
        evaluate_claims=lambda payloads, calibration: quality_spec.evaluate_claims(
            payloads, calibration),
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


class QualitySpecDriftTest(unittest.TestCase):
    def test_real_quality_spec_not_drifted(self):
        self.assertEqual(self_check._quality_spec_drift(quality_spec), [])

    def test_baseline_copy_not_drifted(self):
        self.assertEqual(self_check._quality_spec_drift(_fake_spec()), [])

    def test_threshold_relaxed_detected(self):
        spec = _fake_spec()
        spec.METRICS["match_quality"].thresholds["qualified_win_rate"] = 0.40
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("qualified_win_rate" in item for item in drift), drift)

    def test_sample_floor_relaxed_detected(self):
        spec = _fake_spec()
        spec.SAMPLE_FLOORS["pairwise_min_pairs"] = 20
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("pairwise_min_pairs" in item for item in drift), drift)

    def test_judge_gate_relaxed_detected(self):
        spec = _fake_spec()
        spec.JUDGE_GATES["human_kappa_min"] = 0.30
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("human_kappa_min" in item for item in drift), drift)

    def test_human_calibration_flag_off_detected(self):
        # 隐藏的绕过方式：把语义指标的 human_calibration 改成 False 就不用人工校准
        spec = _fake_spec()
        spec.METRICS["false_reject"].human_calibration = False
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("human_calibration" in item for item in drift), drift)

    def test_protocol_bump_detected(self):
        spec = _fake_spec()
        spec.PROTOCOL_VERSION = "quality-v2-2099-01-01"
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("PROTOCOL_VERSION" in item for item in drift), drift)

    def test_missing_metric_detected(self):
        spec = _fake_spec()
        del spec.METRICS["safety"]
        drift = self_check._quality_spec_drift(spec)
        self.assertTrue(any("safety" in item for item in drift), drift)


class QualityHardcodeScanTest(unittest.TestCase):
    def test_clean_source_passes(self):
        sources = {"quality_pairwise.py": "from pairwise_quality import safe_person\n"}
        self.assertEqual(self_check._scan_quality_hardcode(sources), [])

    def test_hardcoded_scenario_detected(self):
        sources = {"quality_pairwise.py": "SPECIAL = {'V4_03': 'boost'}\n"}
        hits = self_check._scan_quality_hardcode(sources)
        self.assertTrue(any("V4_03" in hit for hit in hits), hits)

    def test_comment_mention_not_flagged(self):
        sources = {"false_reject.py": "# 历史案例 V3_09 不能写进规则\nX = 1\n"}
        self.assertEqual(self_check._scan_quality_hardcode(sources), [])

    def test_string_literal_mention_flagged(self):
        # 字符串字面量里的场景 ID 属于真硬编码，必须报（注释豁免、代码不豁免）
        sources = {"content_faithfulness.py": "NOTE = 'V3_01 的特殊处理'\n"}
        self.assertTrue(self_check._scan_quality_hardcode(sources))


class MaterialGuardTest(unittest.TestCase):
    def test_all_guards_present_passes(self):
        sources = {
            "quality_pairwise.py": "from pairwise_quality import safe_person, assert_safe_material\n",
            "content_faithfulness.py": "from pairwise_quality import assert_safe_material\n",
            "false_reject.py": "from pairwise_quality import assert_safe_material\n",
        }
        self.assertEqual(self_check._material_guard_issues(sources), [])

    def test_missing_assert_gate_detected(self):
        sources = {"quality_pairwise.py": "from pairwise_quality import safe_person\n"}
        issues = self_check._material_guard_issues(sources)
        self.assertTrue(any("assert_safe_material" in issue for issue in issues), issues)

    def test_missing_safe_person_detected(self):
        sources = {"quality_pairwise.py": "from pairwise_quality import assert_safe_material\n"}
        issues = self_check._material_guard_issues(sources)
        self.assertTrue(any("safe_person" in issue for issue in issues), issues)

    def test_dynamic_gate_rejects_forbidden_key(self):
        with self.assertRaises(ValueError):
            self_check.assert_safe_material({"pairs": [{"candidate_a": {"screen_score": 99}}]})
        self_check.assert_safe_material({"pairs": [{"candidate_a": {"gender": "女"}}]})

    def test_builder_calls_guard_passes(self):
        sources = {"quality_pairwise.py":
                   "def build_materials(pairs):\n    assert_safe_material(materials)\n    return materials\n"}
        self.assertEqual(self_check._builder_guard_issues(sources), [])

    def test_builder_without_guard_detected(self):
        sources = {"false_reject.py":
                   "def build_judge_materials(rows):\n    return rows\n"}
        issues = self_check._builder_guard_issues(sources)
        self.assertTrue(any("assert_safe_material" in issue for issue in issues), issues)

    def test_missing_builder_detected(self):
        sources = {"content_faithfulness.py": "def build_items(bundle):\n    return []\n"}
        issues = self_check._builder_guard_issues(sources)
        self.assertTrue(any("build_judge_materials" in issue for issue in issues), issues)


class ClaimGateProbeTest(unittest.TestCase):
    def test_real_spec_probe_all_fail_closed(self):
        self.assertEqual(self_check._claim_gate_probe_failures(quality_spec), [])

    def test_probe_detects_always_allow_gate(self):
        class AlwaysAllowed:
            def evaluate_claims(self, metrics, calibration):
                return {"quality_claim_allowed": True, "per_metric": {}, "reasons": []}

        failures = self_check._claim_gate_probe_failures(AlwaysAllowed())
        self.assertGreaterEqual(len(failures), 5, failures)
        self.assertTrue(any("缺人工校准" in item for item in failures), failures)
        self.assertTrue(any("样本" in item for item in failures), failures)

    def test_probe_detects_always_blocked_gate(self):
        class NeverAllowed:
            def evaluate_claims(self, metrics, calibration):
                return {"quality_claim_allowed": False, "per_metric": {},
                        "reasons": ["blocked"]}

        failures = self_check._claim_gate_probe_failures(NeverAllowed())
        self.assertTrue(any("齐全达线" in item for item in failures), failures)

    def test_claim_gate_missing_calibration_blocked(self):
        payload = self_check._quality_claim_payloads()["match_quality"]
        result = quality_spec.claim_gate("match_quality", payload, None)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["level"], "blocked")

    def test_claim_gate_low_kappa_blocked(self):
        payload = self_check._quality_claim_payloads()["match_quality"]
        calibration = self_check._clean_calibration(human={"kappa": 0.4, "n": 40})
        self.assertFalse(quality_spec.claim_gate("match_quality", payload, calibration)["allowed"])

    def test_claim_gate_insufficient_samples_blocked(self):
        payloads = self_check._quality_claim_payloads()
        payloads["false_reject"]["soft"]["n"] = 5
        result = quality_spec.claim_gate("false_reject", payloads["false_reject"],
                                         self_check._clean_calibration())
        self.assertFalse(result["allowed"])

    def test_claim_gate_healthy_payload_allowed(self):
        payloads = self_check._quality_claim_payloads()
        claims = quality_spec.evaluate_claims(payloads, self_check._clean_calibration())
        self.assertTrue(claims["quality_claim_allowed"], claims["reasons"])


class SelfCheckRegistrationTest(unittest.TestCase):
    def test_new_checks_registered_and_pass(self):
        names = {name for name, _, _ in self_check.CHECKS}
        for name in NEW_CHECK_NAMES:
            self.assertIn(name, names)
        for name, ok, detail in self_check.CHECKS:
            if name in NEW_CHECK_NAMES:
                self.assertTrue(ok, f"{name} 未通过：{detail}")

    def test_existing_checks_not_removed(self):
        # 原有 14 项不得被新检查挤掉（只加不减）
        self.assertGreaterEqual(len(self_check.CHECKS), 18)
        names = {name for name, _, _ in self_check.CHECKS}
        for legacy in ("冻结文件与供给池", "无场景硬编码", "BASELINE 未被放松",
                       "judge 材料白名单", "内容 judge 仪器校验"):
            self.assertIn(legacy, names)

    def test_main_exit_code_zero(self):
        self.assertEqual(self_check.main([]), 0)


if __name__ == "__main__":
    unittest.main()
