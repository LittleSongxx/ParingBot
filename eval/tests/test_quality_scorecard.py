"""质量评分卡回归测试（离线）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import quality_scorecard as qs  # noqa: E402


def scenario(key, target, runs):
    return {
        "key": key,
        "expect": {"requested": 8, "target": target},
        "runs": [{"delivered": delivered, "run_status": status, "wall_seconds": 10.0}
                 for delivered, status in runs],
    }


def write_matrix(path: Path, scenarios: list[dict]) -> Path:
    path.write_text(json.dumps({"scenarios": scenarios}, ensure_ascii=False), encoding="utf-8")
    return path


class ScorecardSummaryTest(unittest.TestCase):
    def _rows(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            first = write_matrix(tmp / "m1.json", [
                scenario("S1", 8, [(8, "已完成"), (8, "已完成")]),
                scenario("S2", 8, [(8, "已完成"), (6, "已完成")]),
            ])
            second = write_matrix(tmp / "m2.json", [
                scenario("S1", 8, [(8, "已完成")]),
                scenario("S2", 8, [(8, "已完成")]),
            ])
            return qs.collect_runs([first, second])

    def test_aggregate_and_unstable(self):
        rows = self._rows()
        self.assertEqual(len(rows), 6)
        summary = qs.summarize_runs(rows)
        self.assertEqual(summary["scenarios"], 2)
        self.assertEqual(summary["scenario_runs"], 6)
        self.assertEqual(summary["failures"], 0)
        self.assertIn("S2", summary["unstable_scenarios"])
        self.assertNotIn("S1", summary["unstable_scenarios"])
        self.assertEqual(summary["per_scenario"]["S2"]["delivered"], [8, 6, 8])
        self.assertTrue(summary["delivery_headroom"])  # S2 有 6/8，整体未到 99%
        self.assertAlmostEqual(summary["same_scenario_consistency"], 0.5)

    def test_failure_rate_has_wilson_ci(self):
        rows = self._rows()
        rows.append({"scenario": "S1", "requested": 8, "target": 8, "delivered": 7,
                     "target_attainment": 0.875, "status": "运行失败",
                     "wall_seconds": 10.0, "source": "x"})
        summary = qs.summarize_runs(rows)
        self.assertEqual(summary["failures"], 1)
        self.assertGreater(summary["failure_rate"], 0)
        self.assertLessEqual(summary["failure_ci95"]["lo"], summary["failure_rate"])
        self.assertGreaterEqual(summary["failure_ci95"]["hi"], summary["failure_rate"])

    def test_content_and_judge_sections(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            content = tmp / "content.json"
            content.write_text(json.dumps({
                "n": 20, "means": {"overall": 4.75, "faithful": 4.65},
                "ci95": {}, "rule_warnings": [1, 2], "ceiling_effect": False,
                "credible": True, "judge_model": "qwen"}), encoding="utf-8")
            judge = tmp / "judge.json"
            judge.write_text(json.dumps({
                "mode": "pairwise", "model": "qwen",
                "aggregate": {"pairs": 21, "valid": 20, "delivered_win_rate": 0.75,
                              "position_consistency": 0.85,
                              "ci95": {"delivered_win_rate": {"lo": 0.53, "hi": 0.89}}}}), encoding="utf-8")
            result = qs.build([], [], [content], [judge])
            self.assertEqual(result["content"]["n"], 20)
            self.assertEqual(result["content"]["rule_warnings"], 2)
            self.assertEqual(result["judge"]["delivered_win_rate"], 0.75)
            self.assertFalse(result["claims"]["quality_claim_allowed"])
            text = qs.render(result)
            self.assertIn("不能声称", text)
            self.assertIn("75.0%", text)


class DiscoverTest(unittest.TestCase):
    def test_discover_artifact_layout(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            matrix_dir = root / "eval" / "reports" / "scenario-matrix-x"
            matrix_dir.mkdir(parents=True)
            (matrix_dir / "matrix.json").write_text("{}", encoding="utf-8")
            (root / "regression-report.json").write_text("{}", encoding="utf-8")
            found = qs._discover(root)
            self.assertIsNotNone(found["matrix"])
            self.assertIsNotNone(found["report"])


if __name__ == "__main__":
    unittest.main()