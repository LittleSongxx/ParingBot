"""A3 审计修复的泄漏回归测试：judge 材料白名单与成对评审 payload。

覆盖：
- safe_person 去掉 delivered_rank/screen_score/audit_status/evidence 等系统元数据；
- safe_person 的 preference 只保留 must/detail，detail 再白名单；
- 含禁字段或 *_role 的任意嵌套 dict/list 经 assert_safe_material 必须 raise；
- pairwise_quality 构造的 judge 材料不含 A_role/B_role，且交付候选已白名单化；
- pairwise_ranking 的 prompt payload 不含 delivered_rank/screen_score 等；
- --control near 选同性别/同片区/硬可匹配且软维度接近的 near-miss。
"""
from __future__ import annotations

import json
import random
import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import pairwise_quality  # noqa: E402
import pairwise_ranking  # noqa: E402
from lib import rules, seed as seedmod  # noqa: E402

FORBIDDEN = pairwise_quality.FORBIDDEN_MATERIAL_KEYS


def raw_candidate(**overrides) -> dict:
    """模拟 bundle 里的原始候选：带齐系统元数据，必须被 safe_person 全部剥掉。"""
    candidate = {
        "id": 861, "nickname": "候选", "gender": "女", "birth_date": "1999-07-20 00:00:00",
        "rent_budget": 4000, "tidiness": "整洁", "occupation": "交付本人",
        "lease_term": "3-6个月", "store_id": 1, "schedule_type": "正常作息",
        "has_pet": "无", "smoking": "不吸烟", "self_intro": "爱干净", "roommate_expectation": "作息规律",
        "interest_tags": ["养猫", "电竞"], "portrait": {"summary": "模型画像"},
        "delivered_rank": 3, "screen_score": 95.5, "delivered": True,
        "audit_status": "通过", "reject_code": "R01", "reject_reason": "理由",
        "delivered_to_user": 8, "evidence": ["合租同性（女）"], "candidate_row_id": 77,
        "found_round": 2, "relax_note": "无",
        "preference": {"age_min": "23", "age_max": "30", "age_required": "必须",
                       "pet_accept": "接受", "audit_status": "preference 里的泄漏"},
    }
    candidate.update(overrides)
    return candidate


def fake_member(member_id: int, **overrides) -> seedmod.Member:
    base = dict(id=member_id, gender="女", rent_budget=4000, tidiness="整洁", occupation="工程师",
                lease_term="3-6个月", store_id=1, schedule_type="正常作息", has_pet="无",
                smoking="不吸烟", self_intro="爱干净", roommate_expectation="作息规律",
                interest_tags=["养猫"], audit_status="已通过", enabled="是")
    base.update(overrides)
    return seedmod.Member(**base)


def fake_seed(members: list) -> seedmod.SeedData:
    return seedmod.SeedData(members=members, preferences={})


def fake_applicant(**overrides) -> dict:
    applicant = {
        "id": 2, "gender": "女", "store_id": 1, "rent_budget": 4000, "tidiness": "整洁",
        "lease_term": "3-6个月", "schedule_type": "正常作息", "has_pet": "无", "smoking": "不吸烟",
        "self_intro": "我作息规律", "roommate_expectation": "希望室友爱干净",
        "interest_tags": ["养猫"],
        "preference": {"detail": {"pet_accept": "不接受", "pet_required": "必须"}},
    }
    applicant.update(overrides)
    return applicant


class SafePersonTest(unittest.TestCase):
    def test_strips_all_system_metadata(self):
        safe = pairwise_quality.safe_person(raw_candidate())
        for key in FORBIDDEN:
            self.assertNotIn(key, safe)
        self.assertNotIn("A_role", safe)
        self.assertNotIn("B_role", safe)
        self.assertFalse([key for key in safe if str(key).endswith("_role")])
        self.assertNotIn("portrait", safe)
        self.assertNotIn("nickname", safe)
        json.dumps(safe, ensure_ascii=False)  # 必须可序列化进 prompt

    def test_keeps_only_whitelisted_fields(self):
        safe = pairwise_quality.safe_person(raw_candidate())
        self.assertEqual(set(safe) - {"preference"}, set(pairwise_quality.SAFE_PERSON_FIELDS))
        self.assertEqual(safe["gender"], "女")
        self.assertEqual(safe["interest_tags"], ["养猫", "电竞"])
        self.assertEqual(safe["occupation"], "交付本人")
        self.assertEqual(safe["store"], rules.area_of(1))
        self.assertEqual(safe["store_name"], rules.store_name(1))
        self.assertEqual(safe["age"], pairwise_quality.age_of("1999-07-20"))

    def test_preference_only_must_and_detail(self):
        preference = {"must": ["age"], "detail": {"pet_accept": "接受", "audit_status": "x"},
                      "delivered_rank": 1, "A_role": "delivered"}
        safe = pairwise_quality.safe_person(raw_candidate(preference=preference))
        self.assertEqual(set(safe["preference"]), {"must", "detail"})
        self.assertEqual(set(safe["preference"]["detail"]), {"pet_accept"})
        self.assertEqual(safe["preference"]["must"], ["age"])
        pairwise_quality.assert_safe_material({"pair": safe})

    def test_flat_bundle_preference_falls_back_to_detail(self):
        safe = pairwise_quality.safe_person(raw_candidate())
        detail = safe["preference"]["detail"]
        self.assertEqual(detail["age_required"], "必须")
        self.assertEqual(detail["pet_accept"], "接受")
        self.assertNotIn("audit_status", detail)


class AssertSafeMaterialTest(unittest.TestCase):
    def test_each_forbidden_key_raises(self):
        for key in FORBIDDEN:
            payload = {"pairs": [{"pair_id": "p1", "A": {"nested": {key: 1}}}]}
            with self.assertRaises(ValueError, msg=key):
                pairwise_quality.assert_safe_material(payload)

    def test_role_keys_raise(self):
        for key in ("A_role", "B_role", "control_role", "delivered_role"):
            with self.assertRaises(ValueError, msg=key):
                pairwise_quality.assert_safe_material([{"pair_id": "p1", key: "x"}])

    def test_clean_payload_passes(self):
        payload = {"pair_id": "p1", "applicant": fake_applicant(),
                   "A": pairwise_quality.safe_person(raw_candidate()),
                   "B": pairwise_quality.safe_person(raw_candidate(id=99))}
        self.assertIsNone(pairwise_quality.assert_safe_material(payload))


class PairwiseQualityMaterialTest(unittest.TestCase):
    def test_build_pairs_has_no_roles_and_no_metadata(self):
        blind = {"p1": {"applicant": fake_applicant(), "candidate": raw_candidate()}}
        key = {"p1": {"delivered": True}}
        data = fake_seed([fake_member(101), fake_member(861, occupation="交付本人"), fake_member(103, gender="男")])
        pairs = pairwise_quality.build_pairs(blind, key, data, limit=5, control="near")
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual(set(pair), {"pair_id", "applicant", "A", "B"})
        dumped = json.dumps(pair, ensure_ascii=False)
        for needle in ("A_role", "B_role", "delivered_rank", "screen_score", "audit_status",
                       "evidence", "candidate_row_id", "found_round", "relax_note"):
            self.assertNotIn(needle, dumped)
        # 交付候选（id=861）已被排除，near 对照只能从其余同性别同片区池里选。
        self.assertNotEqual(pair["B"].get("occupation"), "交付本人")
        self.assertEqual(pair["B"]["gender"], "女")
        self.assertEqual(pair["B"]["store"], rules.area_of(1))
        pairwise_quality.assert_safe_material(pairs)

    def test_workflow_material_has_no_role_fields(self):
        # 复审 2026-11-05 发现的泄漏：旧实现把 A_role/B_role 写进材料；
        # 这里直接检查发送前的 payload（build_pairs 已含 assert_safe_material）。
        blind = {"p1": {"applicant": fake_applicant(), "candidate": raw_candidate()}}
        key = {"p1": {"delivered": True}}
        pairs = pairwise_quality.build_pairs(blind, key, fake_seed([fake_member(101)]), limit=5, control="random")
        swapped = [{"pair_id": pair["pair_id"], "applicant": pair["applicant"],
                    "A": pair["B"], "B": pair["A"]} for pair in pairs]
        pairwise_quality.assert_safe_material(swapped)  # 位置交换也不得带角色字段
        self.assertNotIn('"A_role"', json.dumps(swapped, ensure_ascii=False))


class NearControlTest(unittest.TestCase):
    def test_near_prefers_same_gender_area_and_hard_eligible(self):
        members = [
            fake_member(201),  # 同性别/同片区、软维度接近
            fake_member(202, store_id=5),  # 同性别但不同片区（徐汇）
            fake_member(203, gender="男"),  # 不同性别
            fake_member(204, schedule_type="夜猫子", has_pet="有", smoking="经常",
                        rent_budget=9000, tidiness="随意"),  # 同性别同片区但软维度差/违反必须项
        ]
        chosen = pairwise_quality.pick_control(fake_applicant(), members, {},
                                               random.Random(1), "near")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.id, 201)
        self.assertEqual(chosen.gender, "女")
        self.assertEqual(rules.area_of(chosen.store_id), rules.area_of(1))

    def test_near_falls_back_to_same_scope(self):
        members = [fake_member(301, store_id=5, gender="女")]
        chosen = pairwise_quality.pick_control(fake_applicant(), members, {},
                                               random.Random(1), "near")
        self.assertEqual(chosen.id, 301)  # 无同片区候选时仍能返回（退化路径）

    def test_near_hard_eligibility_excludes_pet_conflict(self):
        # 申请方 pet_required=必须 + pet_accept=不接受：养宠候选必须被硬规则排除
        members = [fake_member(401, has_pet="有"), fake_member(402)]
        chosen = pairwise_quality.pick_control(fake_applicant(), members, {},
                                               random.Random(2), "near")
        self.assertEqual(chosen.id, 402)


def ranking_bundle() -> dict:
    common = {
        "audit_status": "通过", "evidence": ["证据"], "screen_score": 90,
        "gender": "女", "birth_date": "1999-01-01", "rent_budget": 4000, "tidiness": "整洁",
        "lease_term": "3-6个月", "store_id": 1, "schedule_type": "正常作息",
        "has_pet": "无", "smoking": "不吸烟", "self_intro": "自我介绍",
        "roommate_expectation": "期望", "interest_tags": ["养猫"],
        "preference": {"age_min": 23, "age_max": 31},
    }
    top = dict(common, id=1, delivered=True, delivered_rank=1)
    bottom = dict(common, id=2, delivered=True, delivered_rank=5)
    rejected = dict(common, id=3, delivered=False, delivered_rank=None)
    return {
        "meta": {"generated_at": "2026-11-05", "model_configs": [{"model_name": "deepseek-flash"}]},
        "runs": [{"applicant": {"id": 9, "gender": "女", "store_id": 1},
                  "candidates": [top, bottom, rejected]}],
    }


class PairwiseRankingMaterialTest(unittest.TestCase):
    def test_pairs_from_bundle_uses_safe_person(self):
        pairs = pairwise_ranking.pairs_from_bundle(ranking_bundle(), limit=8)
        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertNotIn("id", pair["top"])  # id 不在白名单
        for forbidden in FORBIDDEN:
            self.assertNotIn(forbidden, pair["top"])
            self.assertNotIn(forbidden, pair["bottom"])
        self.assertNotIn("delivered_rank", pair["top"])
        self.assertNotIn("screen_score", pair["bottom"])
        self.assertNotIn("evidence", pair["top"])
        # 审计字段单独保存，不进 prompt
        self.assertEqual(pair["rank_a"]["delivered_rank"], 1)
        self.assertEqual(pair["rank_a"]["candidate_id"], 1)
        self.assertEqual(pair["rank_b"]["candidate_id"], 2)

    def test_prompt_payload_has_no_rank_or_screen_score(self):
        pairs = pairwise_ranking.pairs_from_bundle(ranking_bundle(), limit=8)
        forward, backward = pairwise_ranking.build_payloads(pairs)
        for payload in (forward, backward):
            dumped = json.dumps(payload, ensure_ascii=False)
            for needle in ("delivered_rank", "screen_score", "delivered", "audit_status",
                           "evidence", "candidate_row_id", "A_role", "B_role"):
                self.assertNotIn(needle, dumped)
            pairwise_quality.assert_safe_material(payload)  # 不 raise 才是安全材料

    def test_build_payloads_fails_closed_on_leak(self):
        pairs = [{"pair_id": "R01", "applicant": fake_applicant(),
                  "top": {"gender": "女", "delivered_rank": 1},
                  "bottom": {"gender": "女"},
                  "rank_a": {"candidate_id": 1, "delivered_rank": 1},
                  "rank_b": {"candidate_id": 2, "delivered_rank": 2}}]
        with self.assertRaises(ValueError):
            pairwise_ranking.build_payloads(pairs)

    def test_rows_keep_only_audit_fields(self):
        pairs = pairwise_ranking.pairs_from_bundle(ranking_bundle(), limit=8)
        rows = pairwise_ranking.make_rows(pairs, {"R01": "A"}, {"R01": "B"})
        row = rows[0]
        self.assertEqual(set(row["rank_a"]), {"candidate_id", "delivered_rank"})
        self.assertEqual(set(row["rank_b"]), {"candidate_id", "delivered_rank"})
        self.assertTrue(row["top_win"])
        self.assertEqual(row["backward"], "A")  # backward B => 归一为 A(top)
        summary = pairwise_ranking.summarize(rows)
        self.assertIn("ci95", summary)
        self.assertIn("top_win_rate", summary["ci95"])
        self.assertIn("position_consistency", summary["ci95"])


if __name__ == "__main__":
    unittest.main()
