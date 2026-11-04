import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import analyze_pilot  # noqa: E402


class PilotAnalysisTest(unittest.TestCase):
    def test_pass_k_and_ci(self):
        scenarios = {"scenarios": [
            {"key": "V4_01", "expect": {"requested": 8, "ex_ante_eligible": 8},
             "ex_ante_capacity": {"tier": "high"}},
            {"key": "V4_29", "expect": {"requested": 8, "ex_ante_eligible": 3},
             "ex_ante_capacity": {"tier": "low"}},
        ]}
        matrix = {"scenarios": [
            {"key": "V4_01", "runs": [{"delivered": 8, "run_status": "已完成"},
                                       {"delivered": 8, "run_status": "已完成"},
                                       {"delivered": 8, "run_status": "已完成"}]},
            {"key": "V4_29", "runs": [{"delivered": 3, "run_status": "已完成"},
                                       {"delivered": 3, "run_status": "已完成"},
                                       {"delivered": 3, "run_status": "已完成"}]},
        ]}
        result = analyze_pilot.analyze(matrix, scenarios)
        self.assertEqual(result["scenarios"], 2)
        self.assertEqual(result["pass_full"], 0.5)
        self.assertEqual(result["pass_cap"], 1.0)
        self.assertEqual(result["consistency"], 1.0)
        self.assertLessEqual(result["delivery_ci95"]["lo"], result["delivery_ci95"]["hi"])


if __name__ == "__main__":
    unittest.main()
