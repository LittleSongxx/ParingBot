#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib/seed、lib/rules、lib/metrics、lib/render 的离线单测（不需要 DB / 模型）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.lib import metrics, render, rules, seed as seedmod  # noqa: E402

AS_OF = date(2026, 11, 4)


def make_member(**overrides):
    """构造一位测试租客，默认全部硬条件都填齐。"""
    data = dict(
        id=1, user_id=1, nickname="申请人", gender="男",
        birth_date=date(1996, 5, 20), rent_budget=3500, tidiness="整洁",
        occupation="工程师", lease_term="6-12个月", store_id=1,
        schedule_type="正常作息", has_pet="无", smoking="不吸烟",
        self_intro="介绍", roommate_expectation="期望",
        interest_tags=["看电影", "咖啡"], audit_status="已通过", enabled="是",
    )
    data.update(overrides)
    return seedmod.Member(**data)


def make_pref(**overrides):
    """构造一份默认宽松的合住偏好（全部加分、无约束）。"""
    data = dict(
        member_id=1, age_min=18, age_max=80, age_required="加分",
        budget_min=800, budget_max=20000, budget_required="加分",
        tidiness_min="随意", tidiness_required="加分",
        store_scope="不限", store_required="加分",
        schedule_accept=list(rules.SCHEDULE_TYPES), schedule_required="加分",
        lease_min=None, lease_required="加分",
        pet_accept="无所谓", pet_required="加分",
    )
    data.update(overrides)
    return seedmod.Preference(**data)


def make_bundle(delivered_ids, requested=8, username="u1", member_id=101):
    """构造一份最小 quality bundle：8 位候选，delivered_ids 按给定顺序交付。"""
    delivered_ids = list(delivered_ids)
    candidates = []
    for index in range(1, 9):
        delivered = index in delivered_ids
        candidates.append({
            "id": index, "delivered": delivered,
            "delivered_rank": delivered_ids.index(index) + 1 if delivered else None,
        })
    return {"runs": [{
        "run": {"id": 1, "run_no": "RUN-1", "status": "已完成"},
        "task": {"deliver_count": requested},
        "applicant": {"id": member_id, "username": username, "nickname": "申请人"},
        "candidates": candidates,
    }]}


def make_labels(gold_ids, username="u1", ranked=None):
    ranked = ranked or [{"id": item, "score": 10 - index} for index, item in enumerate(gold_ids)]
    return {"labels": [{"username": username, "gold_ids": list(gold_ids), "ranked": ranked}]}


class SeedParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = seedmod.load_seed(REPO)
        cls.pool = seedmod.approved_candidates(cls.seed)

    def test_repo_seed_loads(self):
        self.assertGreaterEqual(len(self.seed.members), 500)
        self.assertGreaterEqual(len(self.seed.preferences), 500)
        self.assertTrue(self.seed.source.endswith("01-paringbot.sql"))
        self.assertTrue(self.seed.source.replace("\\", "/").endswith(
            "deploy/mysql/sql/base/01-paringbot.sql")
            or self.seed.source.replace("\\", "/").endswith(
                "deploy/mysql/init/01-paringbot.sql"))

    def test_approved_candidates_filter(self):
        self.assertTrue(self.pool)
        for member in self.pool:
            self.assertEqual(member.audit_status, "已通过")
            self.assertEqual(member.enabled, "是")
        ids = [member.id for member in self.seed.members]
        self.assertEqual(ids, sorted(ids))

    def test_member_fields_parsed(self):
        first = self.seed.member(1)
        self.assertIsNotNone(first)
        self.assertEqual(first.nickname, "小宋")
        self.assertEqual(first.gender, "男")
        self.assertEqual(first.birth_date, date(1998, 12, 16))
        self.assertEqual(first.rent_budget, 3500)
        self.assertEqual(first.store_id, 1)
        self.assertEqual(first.interest_tags, ["爬山", "杂志", "品酒", "看电影", "乒乓球"])
        pref = self.seed.preferences[1]
        self.assertEqual(pref.age_min, 23)
        self.assertEqual(pref.age_max, 31)
        self.assertEqual(pref.schedule_accept, ["早睡早起"])
        self.assertEqual(pref.store_scope, "同门店")

    def test_parse_tricky_sql_fixture(self):
        """转义引号、字符串内逗号、NULL、多行元组都要能解析。"""
        sql = """-- fixture
CREATE TABLE `member_profile` (`id` int);
INSERT INTO `member_profile` VALUES (7, 3, 'it''s 名字', '女', '2000-02-29 00:00:00', 3000, '整洁', '教师', '3个月以下', 2, '早睡早起', '无', '不吸烟', 'a,b,c 逗号', NULL, '看电影,咖啡', NULL, '已通过', NULL, NULL, '是', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
INSERT INTO `member_profile` VALUES (8, 4, 'noquote', '男', NULL, NULL, '一般', '会计', '1-2年', 3, '夜猫子', '有', '偶尔', 'x', 'y', '', NULL, '待审核', NULL, NULL, '否', '2026-01-01 00:00:00', '2026-01-01 00:00:00'), (9, 5, 'second', '女', '1999-03-04 00:00:00', 4000, '洁癖', '护士', '2年以上', 4, '正常作息', '无', '不吸烟', 'z', 'w', '跑步', NULL, '已通过', NULL, NULL, '是', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
INSERT INTO `roommate_preference` VALUES (1, 7, 24, 30, '必须', 2000, 4000, '加分', '整洁', '必须', '同片区', '加分', '早睡早起,正常作息', '必须', NULL, '加分', '无所谓', '加分', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deploy" / "mysql" / "sql" / "base" / "01-paringbot.sql"
            path.parent.mkdir(parents=True)
            path.write_text(sql, encoding="utf-8")
            data = seedmod.load_seed(tmp)
        self.assertEqual(len(data.members), 3)
        first = data.members[0]
        self.assertEqual(first.nickname, "it's 名字")
        self.assertEqual(first.self_intro, "a,b,c 逗号")
        self.assertEqual(first.roommate_expectation, "")  # SQL NULL 统一成空串
        self.assertEqual(first.interest_tags, ["看电影", "咖啡"])
        self.assertEqual(first.birth_date, date(2000, 2, 29))
        third = data.members[2]
        self.assertEqual(third.id, 9)
        self.assertEqual(third.rent_budget, 4000)
        self.assertEqual(third.audit_status, "已通过")
        self.assertEqual(data.preferences[7].schedule_accept, ["早睡早起", "正常作息"])

    def test_parse_falls_back_to_old_init_dir(self):
        sql = ("INSERT INTO `member_profile` VALUES (1, 1, 'a', '男', NULL, 1000, '一般', "
               "'x', '1-2年', 1, '正常作息', '无', '不吸烟', 'i', 'e', '', NULL, '已通过', "
               "NULL, NULL, '是', '2026-01-01 00:00:00', '2026-01-01 00:00:00');\n"
               "INSERT INTO `roommate_preference` VALUES (1, 1, 20, 30, '加分', 1000, 3000, "
               "'加分', NULL, '加分', '不限', '加分', '正常作息', '加分', NULL, '加分', "
               "'无所谓', '加分', '2026-01-01 00:00:00', '2026-01-01 00:00:00');\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deploy" / "mysql" / "init" / "01-paringbot.sql"
            path.parent.mkdir(parents=True)
            path.write_text(sql, encoding="utf-8")
            self.assertTrue(seedmod.seed_sql_path(tmp).as_posix().endswith(
                "deploy/mysql/init/01-paringbot.sql"))
            data = seedmod.load_seed(tmp)
        self.assertEqual(len(data.members), 1)

    def test_load_seed_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                seedmod.load_seed(tmp)

    def test_payload_helpers(self):
        member = seedmod.member_from_payload({
            "nickname": "n", "gender": "女", "birth_date": "1999-01-02",
            "rent_budget": 3000, "tidiness": "整洁", "occupation": "x",
            "lease_term": "6-12个月", "store_id": 1, "schedule_type": "正常作息",
            "has_pet": "无", "smoking": "不吸烟", "interest_tags": ["看电影"],
        })
        self.assertEqual(member.birth_date, date(1999, 1, 2))
        self.assertEqual(member.interest_tags, ["看电影"])
        pref = seedmod.preference_from_payload({
            "age_min": 24, "age_max": 30, "age_required": "必须",
            "budget_min": 2500, "budget_max": 3500, "store_scope": "同片区",
            "store_required": "必须", "schedule_accept": ["正常作息"],
            "schedule_required": "必须", "tidiness_min": "不限", "lease_min": "不限",
            "pet_accept": "接受",
        })
        self.assertIsNone(pref.tidiness_min)
        self.assertIsNone(pref.lease_min)
        self.assertEqual(pref.schedule_accept, ["正常作息"])
        self.assertEqual(pref.age_required, "必须")


class RulesTest(unittest.TestCase):
    def test_age_of(self):
        self.assertEqual(rules.age_of(date(2000, 5, 20), AS_OF), 26)
        self.assertEqual(rules.age_of(date(2000, 11, 5), AS_OF), 25)
        self.assertEqual(rules.age_of(date(2000, 11, 4), AS_OF), 26)
        self.assertIsNone(rules.age_of(None, AS_OF))

    def test_term_gap_and_conflict(self):
        self.assertEqual(rules.term_gap("3个月以下", "3个月以下"), 0)
        self.assertEqual(rules.term_gap("3个月以下", "3-6个月"), 1)
        self.assertEqual(rules.term_gap("3个月以下", "6-12个月"), 2)
        self.assertIsNone(rules.term_gap(None, "6-12个月"))
        self.assertIsNone(rules.term_gap("非法", "6-12个月"))
        self.assertTrue(rules.lease_conflict("3个月以下", "6-12个月"))
        self.assertTrue(rules.lease_conflict("3个月以下", "2年以上"))
        self.assertFalse(rules.lease_conflict("3个月以下", "3-6个月"))
        self.assertFalse(rules.lease_conflict(None, "6-12个月"))

    def test_required_constraints_semantics(self):
        pref = make_pref(age_required="必须", age_min=24, age_max=30,
                         store_required="必须", store_scope="不限",
                         tidiness_required="必须", tidiness_min="随意",
                         schedule_required="必须")
        self.assertEqual(rules.required_constraints(pref), ["age"])
        self.assertIn("年龄", rules.DIM_NAMES.values())

    def test_hard_violations_each_dimension(self):
        applicant = make_member()
        candidate = make_member(id=2, store_id=2, tidiness="一般",
                                lease_term="3个月以下", schedule_type="夜猫子",
                                has_pet="有", birth_date=date(1980, 1, 1),
                                rent_budget=9000)
        cases = {
            "年龄": (dict(age_required="必须", age_min=24, age_max=28), {}),
            "预算": (dict(budget_required="必须", budget_min=3000, budget_max=3400), {}),
            "整洁度": (dict(tidiness_required="必须", tidiness_min="洁癖"), {}),
            "门店": (dict(store_required="必须", store_scope="同门店"), {}),
            "作息": (dict(schedule_required="必须", schedule_accept=["早睡早起"]), {}),
            "租期": (dict(lease_required="必须", lease_min="1-2年"), {}),
            # 宠物维度比的是「申请方是否养宠」，所以换一位养宠的申请方
            "宠物态度": (dict(pet_required="必须", pet_accept="不接受"), {"has_pet": "有"}),
        }
        for expected, (overrides, applicant_overrides) in cases.items():
            with self.subTest(dimension=expected):
                pref = make_pref(**overrides)
                current = make_member(**applicant_overrides)
                self.assertEqual(rules.hard_violations(current, candidate, pref, AS_OF),
                                 [expected])

    def test_hard_violations_respects_bonus_and_no_constraint(self):
        applicant = make_member()
        candidate = make_member(id=2, store_id=2, tidiness="一般", has_pet="有",
                                birth_date=date(1980, 1, 1), rent_budget=9000)
        # 加分项不参与硬规则
        bonus = make_pref(age_required="加分", age_min=24, age_max=30,
                          budget_required="加分", budget_min=3000, budget_max=4000,
                          tidiness_required="加分", tidiness_min="整洁",
                          pet_required="加分", pet_accept="不接受")
        self.assertEqual(rules.hard_violations(applicant, candidate, bonus, AS_OF), [])
        # 必须但无约束的取值（不限/无所谓/全选作息/最低档）不算违规
        loose = make_pref(age_required="必须", age_min=24, age_max=28,
                          store_required="必须", store_scope="不限",
                          tidiness_required="必须", tidiness_min="随意",
                          schedule_required="必须", pet_required="必须",
                          pet_accept="无所谓", lease_required="必须")
        # 年龄必须项仍然成立：候选 1980 出生不满足 24-28
        self.assertEqual(rules.hard_violations(applicant, candidate, loose, AS_OF), ["年龄"])

    def test_bidirectional_violations(self):
        applicant = make_member()
        candidate = make_member(id=2, gender="女", lease_term="2年以上",
                                birth_date=date(1980, 1, 1))
        applicant_pref = make_pref(age_required="必须", age_min=24, age_max=30)
        candidate_pref = make_pref(member_id=2)
        found = rules.bidirectional_violations(applicant, applicant_pref,
                                               candidate, candidate_pref, AS_OF)
        self.assertIn("性别", found)
        self.assertIn("租期", found)
        self.assertIn("年龄", found)
        self.assertFalse(rules.is_hard_eligible(applicant, applicant_pref,
                                                candidate, candidate_pref, AS_OF))

    def test_gender_conflict_and_same_place(self):
        self.assertTrue(rules.gender_conflict(make_member(gender="男"),
                                              make_member(id=2, gender="女")))
        self.assertFalse(rules.gender_conflict(make_member(gender="男"),
                                               make_member(id=2, gender="男")))
        # 张江店(1) 与 金桥店(2) 同属浦东片区
        self.assertTrue(rules.same_place(1, 2, "同片区"))
        self.assertFalse(rules.same_place(1, 2, "同门店"))
        self.assertTrue(rules.same_place(1, 1, "同门店"))
        self.assertFalse(rules.same_place(1, 20, "不限"))  # 不限不构成同店/同片区


class MetricsTest(unittest.TestCase):
    def test_delivery_stats(self):
        result = metrics.delivery_stats([
            {"requested": 8, "delivered": 8, "status": "已完成"},
            {"requested": 8, "delivered": 0, "status": "运行失败"},
            {"requested": 8, "delivered": 3, "status": "已完成"},
        ])
        aggregate = result["aggregate"]
        self.assertEqual(aggregate["runs"], 3)
        self.assertEqual(aggregate["requested_total"], 24)
        self.assertEqual(aggregate["delivered_total"], 11)
        self.assertAlmostEqual(aggregate["avg_delivered"], 3.6667)
        self.assertAlmostEqual(aggregate["delivery_rate"], 0.4583)
        self.assertEqual(aggregate["completed"], 2)
        self.assertEqual(aggregate["failed"], 1)
        self.assertEqual(aggregate["short_runs"], 2)
        self.assertEqual(result["runs"][0]["delivered"], 8)

    def test_delivery_stats_bundle_shape(self):
        bundle = make_bundle([1, 2, 3])
        aggregate = metrics.delivery_stats(bundle["runs"])["aggregate"]
        self.assertEqual(aggregate["delivered_total"], 3)
        self.assertEqual(aggregate["requested_total"], 8)

    def test_delivery_stats_matrix_records(self):
        """场景矩阵记录（带 runs 子列表）也能直接统计。"""
        records = [{
            "key": "V3_01",
            "runs": [
                {"delivered": 8, "run_status": "已完成"},
                {"delivered": 6, "run_status": "已完成"},
            ],
        }, {
            "key": "V3_09",
            "run": False,
            "runs": [],
        }]
        result = metrics.delivery_stats(records)
        aggregate = result["aggregate"]
        self.assertEqual(aggregate["runs"], 2)
        self.assertEqual(aggregate["delivered_total"], 14)
        self.assertEqual(aggregate["requested_total"], 16)
        self.assertEqual([row["key"] for row in result["runs"]], ["V3_01", "V3_01"])

    def test_agreement_precision_uses_requested_denominator(self):
        bundle = make_bundle([1])
        labels = make_labels(list(range(1, 9)))
        result = metrics.agreement(bundle, labels)
        row = result["rows"][0]
        self.assertEqual(row["requested"], 8)
        self.assertEqual(row["delivered"], 1)
        self.assertEqual(row["hits"], 1)
        # 只交 1 人但命中：Precision 分母必须是 requested=8，不是 delivered=1
        self.assertAlmostEqual(row["precision"], 0.125)
        self.assertAlmostEqual(row["recall"], 0.125)
        self.assertAlmostEqual(result["aggregate"]["avg_precision"], 0.125)

    def test_agreement_full_delivery(self):
        bundle = make_bundle([1, 2, 3, 4, 5, 6, 7, 8])
        labels = make_labels(list(range(1, 9)))
        result = metrics.agreement(bundle, labels)
        self.assertAlmostEqual(result["aggregate"]["avg_precision"], 1.0)
        self.assertAlmostEqual(result["aggregate"]["avg_recall"], 1.0)

    def test_agreement_skips_unknown_applicant(self):
        bundle = make_bundle([1], username="someone-else")
        result = metrics.agreement(bundle, make_labels(list(range(1, 9))))
        self.assertEqual(result["aggregate"]["runs"], 0)
        self.assertTrue(result["rows"][0]["skipped"])

    def test_ndcg_penalizes_short_delivery(self):
        labels = make_labels(list(range(1, 9)))
        full = metrics.ndcg_penalized(make_bundle(list(range(1, 9))), labels)
        short = metrics.ndcg_penalized(make_bundle([1]), labels)
        self.assertAlmostEqual(full["aggregate"]["avg_ndcg"], 1.0)
        # 1/8 交付不能拿到 1.0；补 0 收益到 K 后应显著低于满交付
        self.assertLess(short["aggregate"]["avg_ndcg"], 0.6)
        self.assertNotAlmostEqual(short["aggregate"]["avg_ndcg"], 1.0)

    def test_ndcg_empty_delivery_is_zero(self):
        result = metrics.ndcg_penalized(make_bundle([]), make_labels(list(range(1, 9))))
        self.assertEqual(result["aggregate"]["avg_ndcg"], 0.0)

    def test_ndcg_grades_follow_ranked_positions(self):
        # gold 里排第 1-2 的收益 3、第 3-5 收益 2、第 6-8 收益 1
        labels = make_labels(list(range(1, 9)))
        result = metrics.ndcg_penalized(make_bundle([8]), labels)
        # 第 8 名收益 1：DCG=1，IDCG≈16.37，比值很小
        self.assertGreater(result["aggregate"]["avg_ndcg"], 0.0)
        self.assertLess(result["aggregate"]["avg_ndcg"], 0.1)

    def test_bootstrap_ci(self):
        values = [0, 1] * 8
        first = metrics.bootstrap_ci(values, iterations=500, seed=7)
        second = metrics.bootstrap_ci(values, iterations=500, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first["n"], 16)
        self.assertAlmostEqual(first["mean"], 0.5)
        self.assertLessEqual(first["lo"], first["hi"])
        self.assertLessEqual(first["lo"], first["mean"])
        self.assertGreaterEqual(first["hi"], first["mean"])
        empty = metrics.bootstrap_ci([], iterations=10)
        self.assertEqual(empty["n"], 0)
        self.assertEqual(empty["lo"], 0.0)

    def test_paired_diff_ci(self):
        left = [0.2, 0.3, 0.4, 0.1, 0.5, 0.2, 0.3, 0.6]
        right = [0.4, 0.3, 0.7, 0.2, 0.8, 0.2, 0.5, 0.9]
        result = metrics.paired_diff_ci(left, right, iterations=300, seed=11)
        self.assertEqual(result["n"], 8)
        expected = sum(b - a for a, b in zip(left, right)) / 8
        self.assertAlmostEqual(result["mean_diff"], expected)
        self.assertLessEqual(result["lo"], result["hi"])
        with self.assertRaises(ValueError):
            metrics.paired_diff_ci([1, 2], [1], iterations=10)

    def test_mde(self):
        value = metrics.mde(1.0, 8)
        self.assertAlmostEqual(value, (1.959963984540054 + 0.8416212335729143) / 8 ** 0.5, places=5)
        self.assertEqual(metrics.mde(1.0, 0), float("inf"))
        self.assertEqual(metrics.mde(0.0, 8), 0.0)


class RenderTest(unittest.TestCase):
    def test_render_report(self):
        result = {
            "title": "v3 回归报告",
            "meta": {"commit": "abc123", "suite": "v3"},
            "gates": {"failed": False, "reasons": []},
            "delivery": {"avg_delivered": 6.5, "requested": 8, "rate": 0.8125},
            "agreement": {"rows": [{"key": "V3_01", "precision": 0.5}],
                          "aggregate": {"avg_precision": 0.5}},
            "ndcg": {"rows": [], "aggregate": {"avg_ndcg": 0.4}},
        }
        text = render.render_report(result)
        self.assertIn("# v3 回归报告", text)
        self.assertIn("## 门禁：通过", text)
        self.assertIn("abc123", text)
        self.assertIn("81.25%", text)
        self.assertIn("V3_01", text)

    def test_render_report_failed_gate(self):
        text = render.render_report({"gates": {"failed": True, "reasons": ["交付不足"]}})
        self.assertIn("## 门禁：失败", text)
        self.assertIn("交付不足", text)

    def test_render_matrix(self):
        records = [
            {"key": "V3_01", "account": "TEST_SCENARIO_V3_01", "title": "基线",
             "status": "已完成", "runs": [{"delivered": 8, "requested": 8, "run_status": "已完成"},
                                        {"delivered": 6, "requested": 8, "run_status": "已完成"}]},
            {"key": "V3_09", "account": "TEST_SCENARIO_V3_09", "title": "无动态",
             "run": False, "expect": {"can_run": False, "blocker": "moment"}},
        ]
        text = render.render_matrix(records)
        self.assertIn("# 场景矩阵", text)
        self.assertIn("V3_01", text)
        self.assertIn("V3_09", text)
        self.assertIn("14", text)  # 8 + 6 交付合计
        self.assertIn("场景数 2", text)


if __name__ == "__main__":
    unittest.main()