"""judge_calibration.py 离线测试（不联网）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import judge_calibration as jc  # noqa: E402


def _pair(pair_id, outcome, stratum="near_miss"):
    base = {"pair_id": pair_id, "stratum": stratum,
            "delivered_win": False, "control_win": False, "tie": False}
    if outcome == "delivered":
        base["delivered_win"] = True
    elif outcome == "control":
        base["control_win"] = True
    elif outcome == "tie":
        base["tie"] = True
    base["consistent_after_swap"] = outcome != "inconsistent"
    return base


def _payload(pairs, position=0.95, judges=("qwen3.7-plus",)):
    payload = {"metric": "match_quality", "protocol": "quality-v1-2026-11-06",
               "judge_version": "judge-v1", "n_pairs": len(pairs),
               "n_pairs_judged": len(pairs), "position_consistency": position,
               "pairs": pairs, "by_judge": {}}
    for model in judges:
        payload["by_judge"][model] = {"win_rate": 0.7, "pairs": pairs}
    return payload


def _anchors(path: Path):
    path.write_text(json.dumps({"items": [
        {"item_id": "b1", "kind": "bad", "judge": 2.0},
        {"item_id": "b2", "kind": "bad", "judge": 2.2},
        {"item_id": "c1", "kind": "clean", "judge": 4.8},
        {"item_id": "c2", "kind": "clean", "judge": 4.9},
    ]}), encoding="utf-8")
    return str(path)


class PairwiseCalibrationTest(unittest.TestCase):
    def test_perfect_alignment_is_usable(self):
        pairs = [_pair(f"p{i}", "delivered" if i % 2 == 0 else "control") for i in range(60)]
        human = {row["pair_id"]: ("delivered" if row["delivered_win"] else "control")
                 for row in pairs}
        with tempfile.TemporaryDirectory() as tmp:
            anchors = _anchors(Path(tmp) / "anchors.json")
            result = jc.calibrate(_payload(pairs), human, metric="match_quality",
                                  human_agreement={"n": 60, "kappa": 0.8},
                                  anchors_path=anchors)
        self.assertTrue(result["usable"], result["reasons"])
        self.assertAlmostEqual(result["judge_human"]["kappa"], 1.0)
        self.assertTrue(result["ppi"]["available"])

    def test_low_kappa_blocks_claim(self):
        pairs = [_pair(f"p{i}", "delivered") for i in range(60)]
        human = {f"p{i}": ("delivered" if i % 2 == 0 else "control") for i in range(60)}
        result = jc.calibrate(_payload(pairs), human, metric="match_quality",
                              human_agreement={"n": 60, "kappa": 0.8})
        self.assertFalse(result["usable"])
        self.assertTrue(any("kappa" in reason for reason in result["reasons"]))

    def test_position_bias_blocks_claim(self):
        pairs = [_pair(f"p{i}", "delivered") for i in range(60)]
        human = {f"p{i}": "delivered" for i in range(60)}
        result = jc.calibrate(_payload(pairs, position=0.6), human, metric="match_quality",
                              human_agreement={"n": 60, "kappa": 0.8})
        self.assertFalse(result["usable"])
        self.assertTrue(any("position" in reason for reason in result["reasons"]))

    def test_missing_annotator_agreement_blocks_claim(self):
        pairs = [_pair(f"p{i}", "delivered") for i in range(60)]
        human = {f"p{i}": "delivered" for i in range(60)}
        result = jc.calibrate(_payload(pairs), human, metric="match_quality")
        self.assertFalse(result["usable"])
        self.assertTrue(any("双人" in reason or "kappa" in reason for reason in result["reasons"]))

    def test_ppi_corrects_judge_optimism(self):
        # judge 全判 delivered；人工子集 20 个里只有 15 个 delivered -> 校正后约 0.75
        pairs = [_pair(f"p{i}", "delivered") for i in range(60)]
        human = {f"p{i}": ("delivered" if i < 15 else "control") for i in range(20)}
        result = jc.calibrate(_payload(pairs), human, metric="match_quality",
                              human_agreement={"n": 60, "kappa": 0.8})
        ppi = result["ppi"]
        self.assertTrue(ppi["available"])
        self.assertGreater(ppi["raw_judge_rate"], 0.99)
        self.assertLess(ppi["corrected_rate"], 0.85)

    def test_human_csv_with_key_is_parsed(self):
        pairs = [_pair(f"p{i}", "delivered") for i in range(60)]
        key = {f"p{i}": {"delivered_side": "A" if i % 2 == 0 else "B"} for i in range(60)}
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "human.csv"
            csv_path.write_text("pair_id,final_winner\n"
                                + "\n".join(f"p{i},{'A' if i % 2 == 0 else 'B'}"
                                            for i in range(60)), encoding="utf-8")
            labels = jc._human_pair_labels(csv_path, key)
        self.assertEqual(labels["p0"], "delivered")
        self.assertEqual(labels["p1"], "delivered")


class ContentCalibrationTest(unittest.TestCase):
    def test_claim_alignment_and_gate(self):
        claims = [{"claim_id": f"c{i}", "label": "supported"} for i in range(60)]
        payload = {"metric": "content_faithfulness", "n_claims": 60, "claims": claims}
        human = {f"c{i}": "supported" for i in range(60)}
        result = jc.calibrate(payload, human, metric="content_faithfulness",
                              human_agreement={"n": 60, "kappa": 0.75})
        self.assertTrue(result["usable"], result["reasons"])
        self.assertAlmostEqual(result["judge_human"]["kappa"], 1.0)

    def test_claim_mismatch_blocks(self):
        claims = [{"claim_id": f"c{i}", "label": "supported"} for i in range(60)]
        payload = {"metric": "content_faithfulness", "n_claims": 60, "claims": claims}
        human = {f"c{i}": ("supported" if i < 30 else "contradicted") for i in range(60)}
        result = jc.calibrate(payload, human, metric="content_faithfulness",
                              human_agreement={"n": 60, "kappa": 0.75})
        self.assertFalse(result["usable"])


class FalseRejectCalibrationTest(unittest.TestCase):
    def test_soft_reject_alignment_and_ppi(self):
        items = [{"item_id": f"r{i}",
                  "label": "reasonable_reject" if i % 2 else "should_pass"}
                 for i in range(60)]
        payload = {"metric": "false_reject", "soft": {"n": 60, "items": items}}
        human = {item["item_id"]: item["label"] for item in items}
        result = jc.calibrate(payload, human, metric="false_reject",
                              human_agreement={"n": 60, "kappa": 0.8})
        self.assertEqual(result["n_labeled"], 60)
        self.assertAlmostEqual(result["judge_human"]["kappa"], 1.0)
        self.assertTrue(result["ppi"]["available"], result["reasons"])
        self.assertTrue(result["usable"], result["reasons"])


class AdapterFormatTest(unittest.TestCase):
    """兼容 quality_pairwise 新版（majority_choice/judges）与 content by_item.claims。"""

    def test_pairwise_majority_choice_format(self):
        pairs = []
        for index in range(60):
            outcome = "delivered" if index % 2 == 0 else "control"
            pairs.append({
                "pair_id": f"p{index}", "stratum": "near_miss",
                "majority_choice": outcome,
                "judges": {"qwen3.7-plus": {"choice": outcome}},
            })
        payload = {"metric": "match_quality", "n_pairs": 60, "n_pairs_judged": 60,
                   "position_consistency": 0.95, "pairs": pairs,
                   "by_judge": {"qwen3.7-plus": {"win_rate": 0.5}}}
        human = {row["pair_id"]: row["majority_choice"] for row in pairs}
        # 单 judge 且未提供 anchors：可用性只取决于 kappa/position/双人一致性
        result = jc.calibrate(payload, human, metric="match_quality",
                              human_agreement={"n": 60, "kappa": 0.8})
        self.assertEqual(result["n_labeled"], 60)
        self.assertAlmostEqual(result["judge_human"]["kappa"], 1.0)
        self.assertTrue(result["usable"], result["reasons"])

    def test_content_by_item_claims_format(self):
        items = [{"item_id": f"i{index}", "claims": [
            {"claim_id": f"c{index}", "label": "supported"}]} for index in range(60)]
        payload = {"metric": "content_faithfulness", "n_claims": 60, "by_item": items}
        human = {f"c{index}": "supported" for index in range(60)}
        result = jc.calibrate(payload, human, metric="content_faithfulness",
                              human_agreement={"n": 60, "kappa": 0.75})
        self.assertEqual(result["n_labeled"], 60)
        self.assertTrue(result["usable"], result["reasons"])


if __name__ == "__main__":
    unittest.main()
