"""内容质量抽样与统计口径回归测试（离线，不调模型）。

覆盖 A3 审计修复：
- 抽样确定性：同一 bundle 每次抽到同一批 item_id；
- 只抽 portrait 非空的 applicant/delivered candidate，返回带 item_id/role 的条目；
- 实际样本数低于 --min-items 时 exit 1（不再输出不可复核的“样本 20 条”）；
- 均值 bootstrap 95% CI 可复现且包住均值。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import content_quality  # noqa: E402


def sample_bundle() -> dict:
    return {
        "meta": {"generated_at": "2026-11-05", "code_commit": "abc"},
        "runs": [
            {
                "applicant": {"id": 1, "gender": "女",
                              "portrait": {"summary": "申请人画像", "lifestyle_tags": "整洁"}},
                "candidates": [
                    {"id": 11, "delivered": True,
                     "portrait": {"summary": "候选画像1", "lifestyle_tags": "规律"}},
                    {"id": 12, "delivered": True, "portrait": None},
                    {"id": 13, "delivered": False, "portrait": {"summary": "未交付画像"}},
                ],
            },
            {
                "applicant": {"id": 2, "gender": "男", "portrait": None},
                "candidates": [
                    {"id": 21, "delivered": True, "portrait": {"summary": "候选画像2"}},
                ],
            },
        ],
    }


class ContentSamplingTest(unittest.TestCase):
    def test_only_portrait_nonempty_delivered_items(self):
        items = content_quality.sample_items(sample_bundle(), 20)
        self.assertEqual(len(items), 3)  # A1 + C1 + C2
        self.assertEqual({item["item_id"] for item in items}, {"A1", "C1", "C2"})
        self.assertTrue(all(item["portrait"] for item in items))
        self.assertTrue(all(item["role"] in ("applicant", "candidate") for item in items))
        self.assertNotIn("未交付画像", json.dumps(items, ensure_ascii=False))

    def test_sampling_is_deterministic(self):
        bundle = sample_bundle()
        first = content_quality.sample_items(bundle, 2)
        second = content_quality.sample_items(bundle, 2)
        self.assertEqual([item["item_id"] for item in first],
                         [item["item_id"] for item in second])
        self.assertEqual(len(first), 2)
        full_ids = {item["item_id"] for item in content_quality.sample_items(bundle, 20)}
        self.assertTrue({item["item_id"] for item in first} <= full_ids)

    def test_min_items_returns_exit_1(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle_path = tmp / "bundle.json"
            bundle_path.write_text(json.dumps(sample_bundle(), ensure_ascii=False), encoding="utf-8")
            code = content_quality.main([
                "--bundle", str(bundle_path),
                "--limit", "20", "--min-items", "10",
                "--env-file", str(tmp / "missing.env"),
            ])
            self.assertEqual(code, 1)

    def test_ceiling_effect_detects_all_fives(self):
        self.assertTrue(content_quality.ceiling_effect([5, 5, 5, 5]))
        self.assertTrue(content_quality.ceiling_effect([5, 5, 5, 4.8]))
        self.assertFalse(content_quality.ceiling_effect([5, 4, 5, 4]))
        self.assertFalse(content_quality.ceiling_effect([]))

    def test_bootstrap_mean_ci_is_reproducible_and_brackets_mean(self):
        values = [3.0, 4.0, 5.0, 4.0, 4.5]
        ci = content_quality.mean_ci(values)
        self.assertEqual(ci["n"], len(values))
        self.assertLessEqual(ci["lo"], ci["mean"])
        self.assertGreaterEqual(ci["hi"], ci["mean"])
        self.assertEqual(ci["lo"], content_quality.mean_ci(values)["lo"])
        self.assertEqual(content_quality.mean_ci([])["n"], 0)


class ContentRuleWarningTest(unittest.TestCase):
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
