#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""负向场景期望校验的离线单测（不需要 DB / 模型 API）。"""
import json
import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import run_matrix  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

INTRO_SCENARIO = {"key": "V3_10", "run": False,
                  "expect": {"can_run": False, "blocker": "intro"}}
MOMENT_SCENARIO = {"key": "V3_09", "run": False,
                   "expect": {"can_run": False, "blocker": "moment"}}


class IntroRejectedTest(unittest.TestCase):
    """intro 负向：保存档案被 API 拒绝，应视为观察到了预期阻断。"""

    def test_api_rejection_is_ok(self):
        record = {
            "key": "V3_10",
            "status": "未运行（负向：档案不完整，API 层拒绝）",
            "api_rejected": True,
            "rejection": {"stage": "profile",
                          "message": "POST /member/saveMy 业务失败：400 自我介绍不能为空"},
            "notes": ["POST /member/saveMy 业务失败：400 自我介绍不能为空"],
        }
        result = run_matrix.check_negative_expectation(INTRO_SCENARIO, record)
        self.assertTrue(result["ok"])
        self.assertEqual(result["observed"], "api_rejected")
        self.assertEqual(result["detail"]["expected_blocker"], "intro")
        self.assertTrue(result["detail"]["rejected"])

    def test_make_negative_record_writes_contract_fields(self):
        record = {"api_rejected": True,
                  "rejection": {"stage": "profile", "message": "400 自我介绍不能为空"}}
        run_matrix._make_negative_record(record, INTRO_SCENARIO, "档案不完整，API 层拒绝")
        self.assertEqual(record["status"], "未运行（负向：档案不完整，API 层拒绝）")
        self.assertTrue(record["expectation_ok"])
        self.assertEqual(record["negative_observed"], "api_rejected")
        self.assertIn("expectation", record)


class MomentBlockerTest(unittest.TestCase):
    """moment 负向：readiness 在 moment 项阻断，blocker 与期望一致。"""

    def test_matching_blocker_is_ok(self):
        record = {"status": "未运行（readiness 阻断）",
                  "readiness": {"can_run": False,
                                "blocker": {"key": "moment", "message": "还没有租客动态"}}}
        result = run_matrix.check_negative_expectation(MOMENT_SCENARIO, record)
        self.assertTrue(result["ok"])
        self.assertEqual(result["observed"], "readiness_blocked")
        self.assertFalse(result["detail"]["can_run"])
        self.assertEqual(result["detail"]["blocker"], "moment")


class UnexpectedCanRunTest(unittest.TestCase):
    """readiness 意外 can_run=True：负向场景不应被判为通过。"""

    def test_can_run_true_fails_expectation(self):
        record = {"status": "未运行（只做前置检查）",
                  "readiness": {"can_run": True, "blocker": None}}
        result = run_matrix.check_negative_expectation(MOMENT_SCENARIO, record)
        self.assertFalse(result["ok"])
        self.assertEqual(result["observed"], "unexpected_can_run")
        self.assertTrue(result["detail"]["can_run"])


class OtherNegativePathsTest(unittest.TestCase):
    def test_blocker_mismatch_is_not_ok(self):
        record = {"status": "未运行（readiness 阻断）",
                  "readiness": {"can_run": False, "blocker": {"key": "profile"}}}
        result = run_matrix.check_negative_expectation(MOMENT_SCENARIO, record)
        self.assertFalse(result["ok"])
        self.assertEqual(result["observed"], "blocker_mismatch")

    def test_precheck_without_evidence_is_not_ok(self):
        # --phase ready 只做前置检查，且没有拒绝证据：不能算通过
        record = {"status": "未运行（只做前置检查）", "readiness": {}}
        result = run_matrix.check_negative_expectation(MOMENT_SCENARIO, record)
        self.assertFalse(result["ok"])
        self.assertEqual(result["observed"], "not_run_without_evidence")

    def test_positive_scenario_is_not_flagged(self):
        scenario = {"key": "V3_01", "run": True, "expect": {"can_run": True}}
        record = {"status": "已运行", "readiness": {"can_run": True}}
        result = run_matrix.check_negative_expectation(scenario, record)
        self.assertFalse(result["ok"])
        self.assertEqual(result["observed"], "unexpected_can_run")


class FrozenNegativeScenarioTest(unittest.TestCase):
    """用真实冻结的 v3 负向场景验证契约（不联网）。"""

    def test_v3_frozen_negatives_are_recognized(self):
        payload = json.loads(
            (REPO / "eval" / "frozen" / "v3" / "scenarios.json").read_text(encoding="utf-8"))
        negatives = [item for item in payload["scenarios"] if item.get("run") is False]
        self.assertEqual(len(negatives), 2)
        for scenario in negatives:
            blocker = (scenario.get("expect") or {}).get("blocker")
            if blocker == "intro":
                record = {"api_rejected": True,
                          "rejection": {"stage": "profile", "message": "400 自我介绍不能为空"}}
            else:
                record = {"status": "未运行（readiness 阻断）",
                          "readiness": {"can_run": False, "blocker": {"key": blocker}}}
            result = run_matrix.check_negative_expectation(scenario, record)
            self.assertTrue(result["ok"], f"{scenario['key']} -> {result}")
            self.assertEqual(result["detail"]["expected_blocker"], blocker)


if __name__ == "__main__":
    unittest.main()
