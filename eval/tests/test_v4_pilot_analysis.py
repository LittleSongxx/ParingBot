import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import analyze_pilot  # noqa: E402

SCENARIOS = {"scenarios": [
    {"key": "V4_01", "expect": {"requested": 8, "target": 8, "ex_ante_eligible": 8},
     "ex_ante_capacity": {"tier": "high"}},
    # expect.target 优先于 min(requested, eligible_unbounded)：target=4
    {"key": "V4_29", "expect": {"requested": 8, "target": 4, "ex_ante_eligible": 3,
                                "ex_ante_unbounded": 8},
     "ex_ante_capacity": {"tier": "low", "eligible_unbounded": 8}},
    # 没有 expect.target：回退 min(8, eligible_unbounded=5) = 5
    {"key": "V4_30", "expect": {"requested": 8},
     "ex_ante_capacity": {"tier": "medium", "eligible_unbounded": 5}},
    {"key": "V4_41", "run": False,
     "expect": {"requested": 8, "can_run": False, "blocker": "moment"}},
]}

MATRIX = {"label": "v4-pilot-123", "scenarios": [
    {"key": "V4_01", "runs": [{"delivered": 8, "run_status": "已完成"},
                               {"delivered": 8, "run_status": "已完成"},
                               {"delivered": 8, "run_status": "已完成"}]},
    {"key": "V4_29", "runs": [{"delivered": 3, "run_status": "已完成"},
                               {"delivered": 3, "run_status": "已完成"},
                               {"delivered": 3, "run_status": "已完成"}]},
    {"key": "V4_30", "runs": [{"delivered": 5, "run_status": "已完成"},
                               {"delivered": 5, "run_status": "已完成"},
                               {"delivered": 5, "run_status": "已完成"}]},
    {"key": "V4_41", "runs": []},
]}


class TargetResolutionTest(unittest.TestCase):
    def test_frozen_expect_target_wins(self):
        self.assertEqual(
            analyze_pilot.resolve_target({"requested": 8, "target": 4},
                                         {"eligible_unbounded": 8}), 4)

    def test_fallback_min_requested_unbounded(self):
        self.assertEqual(analyze_pilot.resolve_target(
            {"requested": 8, "ex_ante_unbounded": 9}, {}), 8)
        self.assertEqual(analyze_pilot.resolve_target(
            {"requested": 8}, {"eligible_unbounded": 5}), 5)
        self.assertEqual(analyze_pilot.resolve_target(
            {"requested": 8, "ex_ante_eligible": 3}, {}), 3)


class PassPowerTest(unittest.TestCase):
    def test_all_k_subsets_enumeration(self):
        groups = {"a": [True, True, True],
                  "b": [True, True, False],
                  "c": [False, True, True]}
        powers = analyze_pilot._enumerate_pass_power(groups)
        self.assertAlmostEqual(powers["pass^2"], 1 / 3, places=4)
        self.assertAlmostEqual(powers["pass^3"], 1 / 3, places=4)
        # trial 数不够 k 的场景不计入
        self.assertNotIn("pass^5", powers)

    def test_single_trial_no_pass_power(self):
        self.assertEqual(analyze_pilot._enumerate_pass_power({"a": [True]}), {})


class PilotAnalysisTest(unittest.TestCase):
    def test_pass_k_ci_target_hash(self):
        result = analyze_pilot.analyze(
            MATRIX, SCENARIOS, scenarios_sha256="abc123", source="v4-pilot-123")
        self.assertEqual(result["scenarios"], 3)  # 负向场景没有 run，不计入
        self.assertEqual(result["trials"], [3])
        # pass_full：只有 V4_01 三个 trial 都达到 requested 8
        self.assertAlmostEqual(result["pass_full"], 1 / 3, places=4)
        # pass_cap：V4_01（target 8）✓、V4_29（target 4，交付 3）✗、V4_30（回退 target 5）✓
        self.assertAlmostEqual(result["pass_cap"], 2 / 3, places=4)
        self.assertEqual(result["consistency"], 1.0)
        self.assertAlmostEqual(result["target_attainment"], (1 + 3 / 4 + 1) / 3, places=4)
        self.assertAlmostEqual(result["delivery_rate"], (1 + 3 / 8 + 5 / 8) / 3, places=4)
        ci = result["delivery_ci95"]
        self.assertLessEqual(ci["lo"], ci["hi"])
        attain_ci = result["target_attainment_ci95"]
        self.assertLessEqual(attain_ci["lo"], attain_ci["hi"])
        self.assertLessEqual(attain_ci["lo"], result["target_attainment"])
        self.assertGreaterEqual(attain_ci["hi"], result["target_attainment"])
        self.assertEqual(result["scenarios_sha256"], "abc123")
        self.assertEqual(result["source"], "v4-pilot-123")
        self.assertEqual([row["target"] for row in result["rows"]], [8, 4, 5])
        self.assertEqual(result["rows"][1]["target_rule"], "expect.target")
        self.assertEqual(result["rows"][2]["target_rule"],
                         "min(requested, eligible_unbounded)")
        self.assertIsInstance(result["pass_power_cap"], dict)


class PilotCliTest(unittest.TestCase):
    def test_main_writes_sha256_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            matrix_path = tmp / "matrix.json"
            scenarios_path = tmp / "scenarios.json"
            matrix_path.write_text(json.dumps(MATRIX, ensure_ascii=False), encoding="utf-8")
            scenarios_path.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding="utf-8")
            out_json = tmp / "report.json"
            out_md = tmp / "report.md"
            code = analyze_pilot.main([
                "--matrix", str(matrix_path),
                "--scenarios", str(scenarios_path),
                "--json", str(out_json),
                "--out", str(out_md),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            expected = hashlib.sha256(scenarios_path.read_bytes()).hexdigest()
            self.assertEqual(payload["scenarios_sha256"], expected)
            self.assertEqual(payload["source"], "v4-pilot-123")
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("v4-pilot-123", text)
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
