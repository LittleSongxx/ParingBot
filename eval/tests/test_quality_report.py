"""quality_report.py 离线测试（不联网）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import quality_report as qr  # noqa: E402
import quality_spec as spec  # noqa: E402


def _payloads():
    return {
        "match_quality": {
            "metric": "match_quality", "n_pairs": 120, "n_pairs_judged": 115,
            "win_rate": 0.72, "win_rate_ci95": {"mean": 0.72, "lo": 0.63, "hi": 0.80,
                                                "n": 115, "method": "wilson"},
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
            "faithful_rate": 0.97, "faithful_ci95": {"mean": 0.97, "lo": 0.945, "hi": 0.985, "n": 300},
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


def _calibration(usable=True, metric="match_quality"):
    return {
        "metric": metric, "usable": usable,
        "human": {"n": 100, "kappa": 0.72, "agreement": 0.84},
        "judge_human": {"n": 100, "kappa": 0.71, "agreement": 0.86},
        "position_consistency": 0.92,
        "reasons": [] if usable else ["judge-human kappa=0.4 < 0.6"],
        "ppi": {"available": True, "raw_judge_rate": 0.72, "corrected_rate": 0.70,
                "lo": 0.60, "hi": 0.79},
    }


def _calibrations(usable=True):
    return {
        "match_quality": _calibration(usable, "match_quality"),
        "content_faithfulness": _calibration(usable, "content_faithfulness"),
        "false_reject": _calibration(usable, "false_reject"),
    }


class QualityReportTest(unittest.TestCase):
    def test_all_metrics_and_claims(self):
        report = qr.build(_payloads(), _calibrations(True), {"code_commit": "abc123"})
        self.assertTrue(report["claims"]["quality_claim_allowed"], report["claims"]["reasons"])
        self.assertEqual(len(report["rows"]), 6)
        for key in spec.ORDER:
            self.assertEqual(report["claims"]["per_metric"][key]["allowed"], True, key)
        text = qr.render(report)
        self.assertIn("质量报告", text)
        self.assertIn("匹配质量胜率", text)
        self.assertIn("可申报", text)

    def test_missing_calibration_blocks_quality_claim(self):
        report = qr.build(_payloads(), None, {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])
        self.assertTrue(report["claims"]["reasons"])

    def test_single_calibration_only_unlocks_its_metric(self):
        # 只提供 match_quality 的校准：content/false_reject 仍必须 blocked
        report = qr.build(_payloads(), _calibration(True), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])
        self.assertFalse(report["claims"]["per_metric"]["content_faithfulness"]["allowed"])
        self.assertFalse(report["claims"]["per_metric"]["false_reject"]["allowed"])

    def test_unusable_calibration_blocks(self):
        report = qr.build(_payloads(), _calibrations(False), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["quality_claim_allowed"])

    def test_small_pairwise_sample_blocks(self):
        payloads = _payloads()
        payloads["match_quality"]["n_pairs"] = 40
        payloads["match_quality"]["n_pairs_judged"] = 40
        report = qr.build(payloads, _calibrations(True), {"code_commit": "abc123"})
        gate = report["claims"]["per_metric"]["match_quality"]
        self.assertFalse(gate["allowed"])
        self.assertTrue(any("样本" in reason for reason in gate["reasons"]))

    def test_missing_metric_is_reported(self):
        payloads = _payloads()
        payloads.pop("safety")
        report = qr.build(payloads, _calibrations(True), {"code_commit": "abc123"})
        self.assertFalse(report["claims"]["per_metric"]["safety"]["allowed"])
        self.assertEqual(report["rows"][-1]["value"], "未测")

    def test_render_is_stable(self):
        report = qr.build(_payloads(), _calibrations(True), {"code_commit": "abc123"})
        first = qr.render(report)
        second = qr.render(report)
        self.assertEqual(first, second)

    def test_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = {}
            payloads = _payloads()
            for key, payload in payloads.items():
                path = tmp / f"{key}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[key] = path
            cal = tmp / "cal.json"
            cal.write_text(json.dumps(_calibrations(True)), encoding="utf-8")
            code = qr.main([
                "--pairwise", str(paths["match_quality"]),
                "--false-reject", str(paths["false_reject"]),
                "--recall", str(paths["delivery_recall"]),
                "--content", str(paths["content_faithfulness"]),
                "--pass-k", str(paths["pass_k"]),
                "--safety", str(paths["safety"]),
                "--calibration", str(cal),
                "--out-md", str(tmp / "report.md"),
                "--out-json", str(tmp / "report.json"),
                "--code-commit", "abc123",
            ])
            self.assertEqual(code, 0)
            data = json.loads((tmp / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(data["claims"]["quality_claim_allowed"])
            self.assertTrue((tmp / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
