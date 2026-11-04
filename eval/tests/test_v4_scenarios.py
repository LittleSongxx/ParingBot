import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import build_v4_scenarios as v4  # noqa: E402


class V4ScenarioTest(unittest.TestCase):
    def test_build_shape_and_diversity(self):
        data = v4.build()
        self.assertEqual(v4.check(data), [])
        self.assertEqual(data["positive_count"], 40)
        self.assertEqual(data["negative_count"], 8)
        grid = data["grid"]
        self.assertEqual(grid["tier_counts"], {"high": 16, "medium": 12, "low": 12})
        self.assertGreaterEqual(grid["diversity"]["stores"], 15)
        self.assertGreaterEqual(grid["diversity"]["lease_terms"], 4)
        self.assertGreaterEqual(grid["diversity"]["male"], 18)
        self.assertGreaterEqual(grid["diversity"]["female"], 18)

    def test_build_is_deterministic_and_frozen_file_matches(self):
        first = v4.dump(v4.build())
        second = v4.dump(v4.build())
        self.assertEqual(first, second)
        frozen = (EVAL / "frozen" / "v4" / "scenarios.json").read_text(encoding="utf-8")
        self.assertEqual(first, frozen)


if __name__ == "__main__":
    unittest.main()
