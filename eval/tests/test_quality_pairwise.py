#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/quality_pairwise.py 的离线单元测试（不打网络）。

覆盖：
- 三档对照构建（near_miss / rejected / random）与每档独立采样、limit 分配、确定性；
- 材料白名单（safe_person / assert_safe_material，fail-closed）与 --emit-materials schema；
- 双向 judge：胜率、tie 记 0.5、位置一致性、双向不一致不计入胜率；
- 多 judge 逐 judge 报告 + 多数票 + Bradley-Terry；
- Wilson/Clopper-Pearson CI、by_stratum/by_judge、usable 门禁（n_errors>20% 或 PC<0.85）；
- fake-verdicts 离线重放、CLI（--dry-run / --fake-verdicts）、无网络保证。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import pairwise_quality  # noqa: E402
import quality_pairwise  # noqa: E402

FORBIDDEN = pairwise_quality.FORBIDDEN_MATERIAL_KEYS
DELIVERED_MARK = "交付方标记"
CONTROL_MARK = "对照方标记"
PRODUCTION_MODEL = "deepseek-flash"

SYSTEM_FIELDS = ("portrait", "moments", "evidence", "screen_score", "delivered_rank",
                 "found_round", "relax_note", "candidate_row_id", "audit_status",
                 "reject_code", "reject_reason", "audit_round", "delivered",
                 "passed", "truncated", "username")


# ---------------------------------------------------------------------------
# 合成 bundle / 假 judge
# ---------------------------------------------------------------------------


def person(member_id: int, **overrides) -> dict:
    """模拟 bundle 候选：带齐系统元数据（构建时必须被白名单剥掉）。"""
    data = {
        "id": member_id,
        "nickname": f"候选{member_id}",
        "gender": "女",
        "birth_date": "1999-01-01 00:00:00",
        "rent_budget": 4000,
        "tidiness": "整洁",
        "occupation": "工程师",
        "lease_term": "3-6个月",
        "store_id": 1,
        "schedule_type": "正常作息",
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": f"我是成员{member_id}",
        "roommate_expectation": "作息规律",
        "interest_tags": ["养猫"],
        "preference": {"age_min": "23", "age_max": "30", "pet_accept": "接受"},
        "portrait": {"summary": "模型画像"},
        "moments": [{"content": "动态"}],
        "evidence": ["合租同性（女）"],
        "screen_score": 90,
        "delivered_rank": None,
        "found_round": 2,
        "relax_note": "无",
        "candidate_row_id": member_id * 10,
        "audit_status": "通过",
        "reject_code": None,
        "reject_reason": None,
        "audit_round": 1,
        "delivered": False,
        "passed": False,
        "truncated": False,
    }
    data.update(overrides)
    return data


def applicant(member_id: int = 2, **overrides) -> dict:
    data = {key: value for key, value in person(member_id).items()
            if key not in SYSTEM_FIELDS}
    data.update(overrides)
    return data


def run_entry(run_id: int, applicant_id: int, candidates: list, deliver_count: int = 8) -> dict:
    return {
        "run": {"id": run_id, "run_no": 1, "status": "已完成"},
        "task": {"id": run_id * 10, "deliver_count": deliver_count},
        "applicant": applicant(applicant_id),
        "candidates": candidates,
    }


def synthetic_bundle() -> dict:
    run1 = [
        person(101, delivered=True, passed=True, self_intro=DELIVERED_MARK + "101"),
        person(102, delivered=True, passed=True, self_intro=DELIVERED_MARK + "102"),
        person(103, passed=True, self_intro=CONTROL_MARK + "103"),            # near_miss
        person(104, truncated=True, self_intro=CONTROL_MARK + "104"),         # near_miss（截断）
        person(105, audit_status="否决", reject_code="PREFERENCE_CONFLICT",
               self_intro=CONTROL_MARK + "105"),                              # rejected
    ]
    run2 = [
        person(201, delivered=True, passed=True, self_intro=DELIVERED_MARK + "201"),
        person(202, delivered=True, passed=True, self_intro=DELIVERED_MARK + "202"),
        person(203, audit_status="否决", reject_code="MISMATCH_HARD",
               self_intro=CONTROL_MARK + "203"),                              # rejected
        person(204, passed=True, self_intro=CONTROL_MARK + "204"),            # near_miss
    ]
    run3 = [
        person(301, delivered=True, passed=True, self_intro=DELIVERED_MARK + "301"),
        person(302, audit_status="否决", self_intro=CONTROL_MARK + "302"),
    ]
    return {
        "generated_at": "2026-11-06",
        "meta": {"model_configs": [{"model_name": PRODUCTION_MODEL}]},
        "runs": [run_entry(1, 2, run1), run_entry(2, 3, run2), run_entry(3, 4, run3)],
    }


def split_prompt_candidates(prompt: str) -> tuple[str, str]:
    _, _, rest = prompt.partition("【候选 A】")
    candidate_a, _, candidate_b = rest.partition("【候选 B】")
    return candidate_a, candidate_b


def delivered_judge(prompt, model=None, env=None):
    """假 judge：选材料里带交付标记的一方（与 A/B 位置无关，双向一致）。"""
    candidate_a, candidate_b = split_prompt_candidates(prompt)
    a_delivered = DELIVERED_MARK in candidate_a
    b_delivered = DELIVERED_MARK in candidate_b
    if a_delivered and not b_delivered:
        return {"winner": "A", "reason": "交付方更合适"}
    if b_delivered and not a_delivered:
        return {"winner": "B", "reason": "交付方更合适"}
    return {"winner": "tie", "reason": "接近"}


def control_judge(prompt, model=None, env=None):
    candidate_a, candidate_b = split_prompt_candidates(prompt)
    a_control = CONTROL_MARK in candidate_a
    b_control = CONTROL_MARK in candidate_b
    if a_control and not b_control:
        return {"winner": "A", "reason": "对照方更合适"}
    if b_control and not a_control:
        return {"winner": "B", "reason": "对照方更合适"}
    return {"winner": "tie", "reason": "接近"}


def tie_judge(prompt, model=None, env=None):
    return {"winner": "tie", "reason": "接近"}


def position_biased_judge(prompt, model=None, env=None):
    return {"winner": "A", "reason": "永远选 A"}


def broken_judge(prompt, model=None, env=None):
    raise RuntimeError("judge 挂了")


def _flip(winner: str) -> str:
    return {"A": "B", "B": "A"}.get(winner, "tie")


def fake_records(pairs: list, *, delivered_loses_strata=(), model=None,
                 skip=(), all_tie=False) -> list:
    """按 pair 构造双向 fake verdicts。

    delivered_loses_strata 里的档位让对照赢；all_tie=True 时全部平局；
    skip 里的 pair 不生成记录（模拟 judge 调用失败）。
    方向一致性由交付侧位置推导，保证 forward/backward 指向同一个人。
    """
    records = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        if pair_id in skip:
            continue
        delivered_side = pair["delivered_side"]
        control_side = "B" if delivered_side == "A" else "A"
        if all_tie:
            winner = "tie"
            backward_winner = "tie"
        else:
            win_side = ("control" if pair["stratum"] in delivered_loses_strata
                        else "delivered")
            winner = delivered_side if win_side == "delivered" else control_side
            backward_winner = _flip(winner)
        records.append({"pair_id": pair_id, "model": model,
                        "direction": "forward", "winner": winner})
        records.append({"pair_id": pair_id, "model": model,
                        "direction": "backward", "winner": backward_winner})
    return records


def run_with_records(bundle=None, *, limit_pairs=6, records=None, models=("fake-judge",),
                     seed=20261106):
    """离线跑 run()：fake verdicts 重放（包一层，减少各测试重复）。"""
    bundle = bundle if bundle is not None else synthetic_bundle()
    return quality_pairwise.run(bundle, models=list(models), fake_verdicts=records or [],
                                limit_pairs=limit_pairs, seed=seed)


def collect_keys(node, out=None) -> set:
    out = out if out is not None else set()
    if isinstance(node, dict):
        for key, value in node.items():
            out.add(str(key))
            collect_keys(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_keys(item, out)
    return out


# ---------------------------------------------------------------------------
# 构建 pair / 分档
# ---------------------------------------------------------------------------


class BuildTest(unittest.TestCase):
    def test_three_strata_balanced_sample(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        self.assertEqual(len(pairs), 6)
        for stratum in quality_pairwise.STRATA:
            self.assertEqual(sum(1 for pair in pairs if pair["stratum"] == stratum), 2,
                             msg=stratum)
        pair_ids = [pair["pair_id"] for pair in pairs]
        self.assertEqual(len(set(pair_ids)), len(pair_ids))
        for pair in pairs:
            self.assertIn(pair["delivered_side"], ("A", "B"))
            self.assertIsNotNone(pair["delivered_id"])
            self.assertIsNotNone(pair["control_id"])
            for field in ("applicant", "candidate_a", "candidate_b"):
                safe = pair[field]
                self.assertNotIn("id", safe)
                self.assertNotIn("nickname", safe)
                self.assertNotIn("portrait", safe)
                for forbidden in FORBIDDEN:
                    self.assertNotIn(forbidden, safe)

    def test_near_miss_is_same_run_and_not_delivered(self):
        bundle = synthetic_bundle()
        pairs = quality_pairwise.build(bundle, limit_pairs=99, seed=20261106)
        run_of = {}
        delivered_ids = set()
        for run in bundle["runs"]:
            for candidate in run["candidates"]:
                run_of[candidate["id"]] = run["run"]["id"]
                if candidate["delivered"]:
                    delivered_ids.add(candidate["id"])
        near = [pair for pair in pairs if pair["stratum"] == "near_miss"]
        self.assertTrue(near)
        for pair in near:
            self.assertEqual(run_of[pair["delivered_id"]], run_of[pair["control_id"]])
            self.assertNotIn(pair["control_id"], delivered_ids)
            self.assertNotEqual(pair["delivered_id"], pair["control_id"])

    def test_rejected_control_is_rejected_candidate(self):
        bundle = synthetic_bundle()
        status = {candidate["id"]: candidate["audit_status"]
                  for run in bundle["runs"] for candidate in run["candidates"]}
        pairs = quality_pairwise.build(bundle, limit_pairs=99, seed=20261106)
        rejected = [pair for pair in pairs if pair["stratum"] == "rejected"]
        self.assertTrue(rejected)
        for pair in rejected:
            self.assertEqual(status[pair["control_id"]], "否决")

    def test_random_control_is_from_other_run(self):
        bundle = synthetic_bundle()
        run_of = {}
        for run in bundle["runs"]:
            for candidate in run["candidates"]:
                run_of[candidate["id"]] = run["run"]["id"]
        pairs = quality_pairwise.build(bundle, limit_pairs=99, seed=20261106)
        random_pairs = [pair for pair in pairs if pair["stratum"] == "random"]
        self.assertTrue(random_pairs)
        for pair in random_pairs:
            self.assertNotEqual(run_of[pair["delivered_id"]], run_of[pair["control_id"]])

    def test_limit_redistributed_when_stratum_empty(self):
        # 只有 delivered + rejected：near_miss 缺档，配额应让给 rejected/random。
        bundle = {
            "runs": [
                run_entry(1, 2, [person(11, delivered=True, passed=True),
                                 person(12, audit_status="否决"),
                                 person(13, audit_status="否决")]),
                run_entry(2, 3, [person(21, delivered=True, passed=True)]),
            ]
        }
        pairs = quality_pairwise.build(bundle, limit_pairs=3, seed=20261106)
        self.assertEqual(len(pairs), 3)
        strata = {pair["stratum"] for pair in pairs}
        self.assertNotIn("near_miss", strata)
        self.assertIn("rejected", strata)
        self.assertIn("random", strata)

    def test_old_bundle_without_passed_field_still_finds_near_miss(self):
        # 旧 bundle 没有 passed/truncated 字段：非交付但 audit_status=通过 也算 near_miss。
        bundle = {
            "runs": [
                run_entry(1, 2, [person(11, delivered=True, audit_status="通过"),
                                 person(12, audit_status="通过"),
                                 person(13, audit_status="否决")]),
                run_entry(2, 3, [person(21, delivered=True, audit_status="通过")]),
            ]
        }
        pairs = quality_pairwise.build(bundle, limit_pairs=6, seed=20261106)
        by_stratum = {}
        for pair in pairs:
            by_stratum.setdefault(pair["stratum"], []).append(pair)
        self.assertIn("near_miss", by_stratum)
        self.assertIn("rejected", by_stratum)
        self.assertIn("random", by_stratum)

    def test_build_deterministic_and_seed_sensitive(self):
        first = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        second = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        self.assertEqual([pair["pair_id"] for pair in first],
                         [pair["pair_id"] for pair in second])
        third = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=7)
        self.assertNotEqual(
            {(pair["pair_id"], pair["delivered_side"]) for pair in first},
            {(pair["pair_id"], pair["delivered_side"]) for pair in third},
        )

    def test_empty_and_no_delivered_bundles(self):
        self.assertEqual(quality_pairwise.build({}), [])
        self.assertEqual(quality_pairwise.build({"runs": []}), [])
        bundle = {"runs": [run_entry(1, 2, [person(11, audit_status="否决")])]}
        self.assertEqual(quality_pairwise.build(bundle), [])

    def test_limit_zero_means_all(self):
        all_pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=99, seed=20261106)
        zero_limit = quality_pairwise.build(synthetic_bundle(), limit_pairs=0, seed=20261106)
        self.assertEqual(len(zero_limit), len(all_pairs))


# ---------------------------------------------------------------------------
# 材料白名单 / emit-materials
# ---------------------------------------------------------------------------


class MaterialsTest(unittest.TestCase):
    def test_emit_materials_schema(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        materials = quality_pairwise.build_materials(pairs)
        self.assertEqual(set(materials), {"protocol", "pairs", "key"})
        self.assertEqual(materials["protocol"], quality_pairwise.PROTOCOL)
        self.assertEqual(len(materials["pairs"]), len(pairs))
        for item in materials["pairs"]:
            self.assertEqual(set(item),
                             {"pair_id", "stratum", "applicant", "candidate_a", "candidate_b"})
        for pair in pairs:
            key = materials["key"][pair["pair_id"]]
            self.assertEqual(set(key), {"delivered_side", "delivered_id",
                                        "control_id", "stratum"})
            self.assertEqual(key["delivered_side"], pair["delivered_side"])
            self.assertEqual(key["stratum"], pair["stratum"])
        pairwise_quality.assert_safe_material(materials)  # 不 raise 即安全

    def test_delivered_side_matches_material_content(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=9, seed=20261106)
        materials = quality_pairwise.build_materials(pairs)
        for item in materials["pairs"]:
            pair = next(entry for entry in pairs if entry["pair_id"] == item["pair_id"])
            delivered_side = materials["key"][item["pair_id"]]["delivered_side"]
            candidate = item["candidate_a"] if delivered_side == "A" else item["candidate_b"]
            control = item["candidate_b"] if delivered_side == "A" else item["candidate_a"]
            self.assertIn(DELIVERED_MARK, candidate["self_intro"])
            # random 档的对照来自其他 run，可能是别人家的交付候选；同 run 档必是纯对照。
            if pair["stratum"] != "random":
                self.assertIn(CONTROL_MARK, control["self_intro"])

    def test_materials_have_no_system_metadata(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=9, seed=20261106)
        materials = quality_pairwise.build_materials(pairs)
        dumped = json.dumps(materials, ensure_ascii=False)
        keys = collect_keys(materials)
        for forbidden in FORBIDDEN:
            self.assertNotIn(forbidden, keys, msg=forbidden)
        for key in keys:
            self.assertFalse(key.endswith("_role"), msg=key)
        for leaked in ("portrait", "moments", "nickname", "screen_score", "evidence"):
            self.assertNotIn(leaked, dumped)

    def test_build_materials_fail_closed_on_leak(self):
        pair = {
            "pair_id": "p1", "stratum": "near_miss", "delivered_id": 1, "control_id": 2,
            "delivered_side": "A", "applicant": applicant(2),
            "candidate_a": person(11), "candidate_b": person(12),
        }
        with mock.patch.object(pairwise_quality, "safe_person",
                               side_effect=lambda payload: {"delivered_rank": 1}):
            with self.assertRaises(ValueError):
                quality_pairwise.build_materials([pair])

    def test_judge_prompt_has_no_system_metadata(self):
        prompts = []

        def capture(prompt, model=None, env=None):
            prompts.append(prompt)
            return {"winner": "tie", "reason": "看材料"}

        quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                             judge_fn=capture, limit_pairs=6, seed=20261106)
        self.assertTrue(prompts)
        for prompt in prompts:
            for needle in ("audit_status", "screen_score", "delivered_rank", "evidence",
                           "candidate_row_id", "reject_code", "found_round", "relax_note",
                           "A_role", "B_role", "portrait", "nickname"):
                self.assertNotIn(needle, prompt, msg=needle)


# ---------------------------------------------------------------------------
# 双向 judge / 胜率 / 位置一致性
# ---------------------------------------------------------------------------


class JudgeAggregationTest(unittest.TestCase):
    def test_delivered_wins_all(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs))
        self.assertEqual(report["n_pairs"], 6)
        self.assertEqual(report["n_pairs_judged"], 6)
        self.assertEqual(report["n_errors"], 0)
        self.assertEqual(report["delivered_wins"], 6)
        self.assertEqual(report["control_wins"], 0)
        self.assertEqual(report["ties"], 0)
        self.assertEqual(report["inconsistent"], 0)
        self.assertEqual(report["win_rate"], 1.0)
        self.assertEqual(report["position_consistency"], 1.0)
        self.assertTrue(report["usable"])
        self.assertEqual(report["reasons"], [])

    def test_control_wins_all(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = fake_records(pairs, delivered_loses_strata=quality_pairwise.STRATA)
        report = run_with_records(records=records)
        self.assertEqual(report["delivered_wins"], 0)
        self.assertEqual(report["control_wins"], 6)
        self.assertEqual(report["win_rate"], 0.0)
        self.assertEqual(report["position_consistency"], 1.0)
        self.assertTrue(report["usable"])

    def test_tie_counts_half(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs, all_tie=True))
        self.assertEqual(report["ties"], 6)
        self.assertEqual(report["win_rate"], 0.5)
        self.assertEqual(report["position_consistency"], 1.0)
        self.assertTrue(report["usable"])

    def test_position_bias_is_inconsistent_and_unusable(self):
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      judge_fn=position_biased_judge, limit_pairs=6,
                                      seed=20261106)
        self.assertEqual(report["inconsistent"], 6)
        self.assertEqual(report["delivered_wins"], 0)
        self.assertEqual(report["control_wins"], 0)
        self.assertEqual(report["win_rate"], None)
        self.assertEqual(report["position_consistency"], 0.0)
        self.assertFalse(report["usable"])
        self.assertTrue(any("位置一致性" in reason for reason in report["reasons"]))

    def test_all_errors_unusable(self):
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      judge_fn=broken_judge, limit_pairs=6, seed=20261106)
        self.assertEqual(report["n_errors"], 6)
        self.assertEqual(report["error_rate"], 1.0)
        self.assertFalse(report["usable"])
        self.assertTrue(any("失败率" in reason for reason in report["reasons"]))

    def test_partial_errors_under_threshold_still_usable(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = fake_records(pairs[:-1])  # 少 1 对 = 16.7% < 20%
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      fake_verdicts=records, limit_pairs=6, seed=20261106)
        self.assertEqual(report["n_errors"], 1)
        self.assertEqual(report["n_pairs_judged"], 5)
        self.assertEqual(report["delivered_wins"], 5)
        self.assertTrue(report["usable"])

    def test_errors_over_threshold_unusable(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = fake_records(pairs[:4])  # 2 对失败 = 33.3% > 20%
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      fake_verdicts=records, limit_pairs=6, seed=20261106)
        self.assertEqual(report["n_errors"], 2)
        self.assertAlmostEqual(report["error_rate"], 0.3333, places=4)
        self.assertFalse(report["usable"])
        self.assertTrue(any("失败率" in reason for reason in report["reasons"]))


# ---------------------------------------------------------------------------
# 多 judge / 多数票 / Bradley-Terry / by_stratum
# ---------------------------------------------------------------------------


class MultiJudgeTest(unittest.TestCase):
    def test_majority_vote_and_by_judge(self):
        # 只用 near_miss/rejected（同 run 对照）保证标记判官可确定辨认交付侧。
        pairs = [pair for pair in quality_pairwise.build(
            synthetic_bundle(), limit_pairs=99, seed=20261106)
            if pair["stratum"] != "random"]
        models = ["judge-delivered-a", "judge-delivered-b", "judge-control"]
        details = quality_pairwise.judge_pairs(pairs, models=models,
                                               judge_fn=_dispatch_judge)
        report = quality_pairwise.summarize(details, models=models,
                                            seed=20261106, limit_pairs=len(pairs))
        self.assertEqual(set(report["by_judge"]), set(models))
        self.assertEqual(report["by_judge"]["judge-delivered-a"]["win_rate"], 1.0)
        self.assertEqual(report["by_judge"]["judge-delivered-b"]["win_rate"], 1.0)
        self.assertEqual(report["by_judge"]["judge-control"]["win_rate"], 0.0)
        self.assertEqual(report["delivered_wins"], len(pairs))
        self.assertEqual(report["win_rate"], 1.0)
        self.assertEqual(report["majority_vote"]["delivered"], len(pairs))
        self.assertEqual(report["position_consistency"], 1.0)
        self.assertEqual(report["judgement"]["aggregation"], "majority_vote")

    def test_majority_split_is_unresolved(self):
        # 两个 judge 各投一边（1:1）→ 多数票无结论，不计入胜率。
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=2, seed=20261106)
        models = ["judge-delivered", "judge-control"]
        details = quality_pairwise.judge_pairs(pairs, models=models,
                                               judge_fn=_dispatch_judge)
        report = quality_pairwise.summarize(details, models=models,
                                            seed=20261106, limit_pairs=2)
        self.assertEqual(report["inconsistent"], 2)
        self.assertIsNone(report["win_rate"])
        self.assertFalse(report["usable"])

    def test_bradley_terry_orders_strata(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = fake_records(pairs, delivered_loses_strata=("near_miss",))
        report = run_with_records(records=records)
        self.assertEqual(report["by_stratum"]["near_miss"]["control_wins"], 2)
        self.assertEqual(report["by_stratum"]["rejected"]["delivered_wins"], 2)
        self.assertEqual(report["by_stratum"]["random"]["delivered_wins"], 2)
        strengths = report["bradley_terry"]["strengths"]
        self.assertIn("delivered", strengths)
        self.assertIn("control:near_miss", strengths)
        self.assertGreater(strengths["control:near_miss"], strengths["delivered"])
        self.assertGreater(strengths["delivered"], strengths["control:rejected"])
        self.assertGreater(strengths["delivered"], strengths["control:random"])

    def test_by_stratum_has_all_three_keys(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs))
        for stratum in quality_pairwise.STRATA:
            bucket = report["by_stratum"][stratum]
            self.assertEqual(bucket["n_pairs"], 2)
            self.assertEqual(bucket["win_rate"], 1.0)
            self.assertIn("win_rate_ci95", bucket)
            self.assertIn("position_consistency", bucket)
        self.assertEqual(report["by_stratum"]["near_miss"]["delivered_wins"], 2)


def _dispatch_judge(prompt, model=None, env=None):
    if model == "judge-control":
        return control_judge(prompt)
    return delivered_judge(prompt)


# ---------------------------------------------------------------------------
# 报告 schema / CI / fake 格式 / 注入签名
# ---------------------------------------------------------------------------


class ReportSchemaTest(unittest.TestCase):
    def test_required_fields_and_ci(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs))
        required = ("metric", "protocol", "judge_version", "judgement", "n_pairs",
                    "n_pairs_judged", "n_errors", "delivered_wins", "control_wins",
                    "ties", "inconsistent", "win_rate", "win_rate_ci95",
                    "position_consistency", "position_consistency_ci95",
                    "by_stratum", "by_judge", "bradley_terry", "pairs",
                    "materials_safe", "usable", "reasons")
        for field in required:
            self.assertIn(field, report, msg=field)
        self.assertEqual(report["metric"], "match_quality")
        self.assertEqual(report["protocol"], "quality-v1-2026-11-06")
        self.assertEqual(report["judge_version"], "judge-v1")
        self.assertTrue(report["materials_safe"])
        ci = report["win_rate_ci95"]
        self.assertEqual(ci["method"], "wilson")
        self.assertEqual(ci["n"], 6)
        self.assertLessEqual(ci["lo"], ci["mean"])
        self.assertGreaterEqual(ci["hi"], ci["mean"])
        self.assertIn("clopper_pearson", ci)
        self.assertEqual(ci["clopper_pearson"]["n"], 6)
        position_ci = report["position_consistency_ci95"]
        self.assertEqual(position_ci["n"], 6)
        self.assertIn("clopper_pearson", position_ci)

    def test_pairs_detail_contains_verdicts(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs))
        for detail in report["pairs"]:
            self.assertIn("judges", detail)
            self.assertIn("verdicts", detail)
            self.assertEqual(len(detail["verdicts"]), 2)  # 双向
            judge = detail["judges"]["fake-judge"]
            self.assertIn("forward", judge)
            self.assertIn("backward", judge)
            self.assertTrue(judge["consistent"])
            self.assertEqual(detail["majority_choice"], "delivered")

    def test_sample_floor_and_warnings(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs))
        self.assertFalse(report["sample_floor"]["ok"])
        self.assertTrue(report["warnings"])
        self.assertTrue(any("样本量" in warning for warning in report["warnings"]))

    def test_judge_independence_flag(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        report = run_with_records(records=fake_records(pairs), models=[PRODUCTION_MODEL])
        independence = report["judgement"]["judge_independence"]
        self.assertFalse(independence["independent"])
        self.assertIn(PRODUCTION_MODEL, independence["same_models"])
        self.assertTrue(any("生产模型" in warning for warning in report["warnings"]))

    def test_fake_verdicts_list_and_shorthand_formats(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = fake_records(pairs)  # 未指定 model → 通配
        loaded = quality_pairwise.load_fake_verdicts(records)
        self.assertEqual(len(loaded), 12)
        self.assertIn((None, pairs[0]["pair_id"], "forward"), loaded)
        self.assertIn((None, pairs[0]["pair_id"], "backward"), loaded)
        with_model = quality_pairwise.load_fake_verdicts(
            fake_records(pairs, model="qwen3.7-plus"))
        self.assertIn(("qwen3.7-plus", pairs[0]["pair_id"], "forward"), with_model)
        shorthand_pipe = quality_pairwise.load_fake_verdicts(
            {f"{pairs[0]['pair_id']}|forward": "A"})
        self.assertEqual(len(shorthand_pipe), 1)
        shorthand_nested = quality_pairwise.load_fake_verdicts(
            {pairs[0]["pair_id"]: {"forward": "A", "backward": "B"}})
        self.assertEqual(len(shorthand_nested), 2)
        wrapped = quality_pairwise.load_fake_verdicts({"verdicts": records})
        self.assertEqual(len(wrapped), 12)

    def test_fake_missing_backward_is_error_not_mirrored(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        records = [{"pair_id": pairs[0]["pair_id"], "direction": "forward", "winner": "A"}]
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      fake_verdicts=records, limit_pairs=6,
                                      seed=20261106)
        self.assertGreaterEqual(report["n_errors"], 5)
        self.assertFalse(report["usable"])

    def test_injected_judge_signatures(self):
        outputs = {"one": 0, "two": 0, "three": 0}

        def one(prompt):
            outputs["one"] += 1
            return "tie"

        def two(prompt, model):
            outputs["two"] += 1
            return {"winner": "tie"}

        def three(prompt, model, env):
            outputs["three"] += 1
            return {"winner": "tie", "reason": "ok"}

        for name, fn in (("one", one), ("two", two), ("three", three)):
            report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                          judge_fn=fn, limit_pairs=2, seed=20261106)
            self.assertEqual(report["ties"], 2, msg=name)
            self.assertGreater(outputs[name], 0)

    def test_string_winner_response_parsed(self):
        report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                      judge_fn=lambda prompt, model=None, env=None: "A",
                                      limit_pairs=2, seed=20261106)
        self.assertEqual(report["n_errors"], 0)

    def test_no_network_in_fake_mode(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=4, seed=20261106)
        records = fake_records(pairs)
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("测试禁止网络调用")):
            report = quality_pairwise.run(synthetic_bundle(), models=["fake-judge"],
                                          fake_verdicts=records, limit_pairs=4,
                                          seed=20261106)
            self.assertEqual(report["n_pairs"], 4)
            self.assertEqual(report["n_errors"], 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle_path = self.tmp / "bundle.json"
        self.bundle_path.write_text(json.dumps(synthetic_bundle(), ensure_ascii=False),
                                    encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_cli_dry_run_offline(self):
        out = self.tmp / "out.json"
        materials_path = self.tmp / "materials.json"
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("dry-run 禁止网络")):
            code = quality_pairwise.main([
                "--bundle", str(self.bundle_path), "--out", str(out),
                "--emit-materials", str(materials_path), "--limit-pairs", "6",
                "--seed", "20261106", "--dry-run",
            ])
        self.assertEqual(code, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(report["judgement"]["dry_run"])
        self.assertEqual(report["n_pairs"], 6)
        self.assertEqual(report["n_pairs_judged"], 0)
        self.assertIsNone(report["win_rate"])
        self.assertFalse(report["usable"])
        self.assertTrue(any("dry_run" in reason for reason in report["reasons"]))
        materials = json.loads(materials_path.read_text(encoding="utf-8"))
        self.assertEqual(set(materials), {"protocol", "pairs", "key"})
        self.assertEqual(len(materials["pairs"]), 6)
        pairwise_quality.assert_safe_material(materials)

    def test_cli_fake_verdicts(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=6, seed=20261106)
        fake_path = self.tmp / "fake.json"
        fake_path.write_text(json.dumps(fake_records(pairs), ensure_ascii=False),
                             encoding="utf-8")
        out = self.tmp / "out.json"
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("fake 模式禁止网络")):
            code = quality_pairwise.main([
                "--bundle", str(self.bundle_path), "--out", str(out),
                "--fake-verdicts", str(fake_path), "--limit-pairs", "6",
                "--judge-model", "fake-judge", "--seed", "20261106",
            ])
        self.assertEqual(code, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["win_rate"], 1.0)
        self.assertEqual(report["judgement"]["judges"], ["fake-judge"])
        self.assertFalse(report["judgement"]["fake_verdicts"] is False)
        self.assertTrue(report["usable"])

    def test_cli_rejects_missing_bundle(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("禁止网络")):
            with self.assertRaises(SystemExit):
                quality_pairwise.main(["--bundle", str(self.tmp / "nope.json"),
                                       "--dry-run"])

    def test_cli_judge_model_repeated_and_comma(self):
        pairs = quality_pairwise.build(synthetic_bundle(), limit_pairs=4, seed=20261106)
        fake_path = self.tmp / "fake.json"
        fake_path.write_text(json.dumps(fake_records(pairs), ensure_ascii=False),
                             encoding="utf-8")
        out = self.tmp / "out.json"
        code = quality_pairwise.main([
            "--bundle", str(self.bundle_path), "--out", str(out),
            "--fake-verdicts", str(fake_path), "--limit-pairs", "4",
            "--judge-model", "judge-a,judge-b", "--judge-model", "judge-c",
            "--seed", "20261106",
        ])
        self.assertEqual(code, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["judgement"]["judges"], ["judge-a", "judge-b", "judge-c"])


if __name__ == "__main__":
    unittest.main()
