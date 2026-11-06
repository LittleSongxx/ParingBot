"""judge.py pairwise 胜率口径回归测试（不联网）。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import judge  # noqa: E402


def _row():
    return {
        "run": {"candidates": [
            {"nickname": "delivered", "delivered": True},
            {"nickname": "control", "delivered": False},
        ]},
        "applicant": {"nickname": "applicant"},
        "candidate": {"nickname": "delivered"},
    }


class JudgePairwiseCountTest(unittest.TestCase):
    def test_counts_delivered_wins_not_consistency(self):
        rows = [_row() for _ in range(4)]
        # 每个 pair 两次调用（正序/交换后）。A,B=交付赢；B,A=对照赢；A,A=不一致；tie,tie=平局。
        script = [{"winner": "A"}, {"winner": "B"},
                  {"winner": "B"}, {"winner": "A"},
                  {"winner": "A"}, {"winner": "A"},
                  {"winner": "tie"}, {"winner": "tie"}]
        with patch.object(judge, "call", side_effect=script):
            result = judge.pairwise(rows, "judge", "http://x", "k")
        agg = result["aggregate"]
        self.assertEqual(agg["valid"], 4)
        self.assertEqual(agg["delivered_wins"], 1)
        self.assertEqual(agg["control_wins"], 1)
        self.assertEqual(agg["ties"], 1)
        self.assertEqual(agg["inconsistent"], 1)
        self.assertEqual(agg["delivered_win_rate"], 0.375)
        self.assertEqual(agg["position_consistency"], 0.75)
        # 旧 bug 会把 win_rate 写成 consistency（0.75），这里必须不同。
        self.assertNotEqual(agg["delivered_win_rate"], agg["position_consistency"])


if __name__ == "__main__":
    unittest.main()