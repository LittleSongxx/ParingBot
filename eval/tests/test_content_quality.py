import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import content_quality  # noqa: E402


class ContentQualityTest(unittest.TestCase):
    def test_rule_warning_ignores_negation(self):
        items = [
            {"item_id": "A1", "profile": {"has_pet": "无", "smoking": "不吸烟"},
             "portrait": {"summary": "不养宠物，作息规律", "lifestyle_tags": "不吸烟不养宠"}},
            {"item_id": "A2", "profile": {"has_pet": "无", "smoking": "不吸烟"},
             "portrait": {"summary": "平时喜欢养猫", "lifestyle_tags": "宠物"}},
        ]
        warnings = content_quality.rule_warnings(items)
        self.assertEqual([w["item_id"] for w in warnings], ["A2"])


if __name__ == "__main__":
    unittest.main()
