#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容忠实度（claim 级）离线测试：不联网、不读 .env、不依赖 backend。

覆盖：
- 原文包含校验（归一化后 quote 找不到 → 降级 not_supported）；
- faithful / 矛盾率 / 证据覆盖 / required_dim_coverage 与 CP 区间；
- 确定性规则兜底（宠物/预算/租期/门店/吸烟）与 rule_warnings；
- --dry-run / --fake-json 离线 CLI、人工校准 CSV 列契约；
- 材料白名单（系统元数据不得进 judge 材料）；
- judge 失败 / 部分缺返回时的 usable 门禁。
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import content_faithfulness as cf  # noqa: E402
import quality_spec  # noqa: E402


# ---------------------------------------------------------------------------
# 合成 bundle
# ---------------------------------------------------------------------------
def make_bundle() -> dict:
    applicant = {
        "id": 100,
        "username": "TEST_T6_CF",
        "nickname": "申请方甲",
        "gender": "女",
        "birth_date": "1995-01-01 00:00:00",
        "rent_budget": 4000,
        "tidiness": "整洁",
        "occupation": "财务",
        "lease_term": "3个月以下",
        "store_id": 1,
        "schedule_type": "正常作息",
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": "我预算4000元，不吸烟，希望找同一家门店的室友。",
        "roommate_expectation": "希望室友作息规律。",
        "interest_tags": "主机游戏,海岛游",
        "preference": {
            "age_required": "加分", "budget_required": "加分", "tidiness_required": "加分",
            "store_required": "加分", "schedule_required": "必须", "lease_required": "加分",
            "pet_required": "加分", "schedule_accept": "正常作息",
        },
        "portrait": {
            "version": 1,
            "summary": "预算4000元，不吸烟，无宠物，计划租期3个月以下，意向张江店",
            "lifestyle_tags": "作息规律,爱干净",
        },
        "moments": [
            {"content": "最近在张江店附近看房。", "time": "2026-11-01 10:00:00"},
            {"content": "下班回家做了个简单的晚饭。", "time": "2026-11-02 10:00:00"},
        ],
    }
    delivered = {
        "id": 201,
        "nickname": "候选甲",
        "gender": "女",
        "birth_date": "1994-02-02 00:00:00",
        "rent_budget": 4000,
        "tidiness": "整洁",
        "occupation": "运营",
        "lease_term": "3-6个月",
        "store_id": 1,
        "schedule_type": "正常作息",
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": "候选甲自我介绍：预算4000元。",
        "roommate_expectation": "希望安静。",
        "interest_tags": "电影,徒步",
        "preference": {"age_required": "加分"},
        "portrait": {"summary": "预算5000元，我养了一只猫", "lifestyle_tags": "爱干净"},
        "moments": [{"content": "周末去徒步了。", "time": "2026-11-01 10:00:00"}],
        "delivered": True,
        "delivered_rank": 1,
        "audit_status": "通过",
        "reject_code": None,
        "reject_reason": None,
    }
    rejected = {
        "id": 202,
        "nickname": "候选乙",
        "gender": "男",
        "birth_date": "1985-03-03 00:00:00",
        "rent_budget": 3000,
        "tidiness": "一般",
        "occupation": "设计",
        "lease_term": "3-6个月",
        "store_id": 2,
        "schedule_type": "正常作息",
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": "候选乙自我介绍。",
        "roommate_expectation": "希望安静。",
        "interest_tags": "摄影",
        "preference": {
            "age_required": "必须", "age_min": 40, "age_max": 50,
        },
        "portrait": None,
        "moments": [],
        "delivered": False,
        "audit_status": "否决",
        "reject_code": "MISMATCH_HARD",
        "reject_reason": "申请方不满足候选方标为必须的条件：年龄",
    }
    return {
        "generated_at": "2026-11-06 10:00:00",
        "meta": {"generated_at": "2026-11-06 10:00:00", "code_commit": "test-bundle"},
        "runs": [{
            "run": {"id": 1, "run_no": "MATCH-TEST-CF", "status": "已完成",
                    "total_round": 2,
                    "summary": "调度 2 轮，候选池累计 2 人，通过审核 1 人，"
                               "否决 1 人，交付 1 人（要求 1 人）"},
            "task": {"id": 1, "deliver_count": 1},
            "applicant": applicant,
            "deliverable_passed_count": 1,
            "delivered_to_user": 1,
            "truncated_count": 0,
            "candidates": [delivered, rejected],
            "rounds": [],
            "funnel": {"stages": []},
        }],
    }


# fake judge：按 item 类型给出 claim；quote 部分故意给出找不到的片段
def fake_judge_outputs(materials: list[dict]) -> dict:
    outputs = {}
    for material in materials:
        kind = material["kind"]
        if kind == "applicant_portrait":
            claims = [
                {"claim": "申请人月租预算 4000 元", "label": "supported", "quote": "预算4000"},
                {"claim": "申请人吸烟", "label": "contradicted", "quote": "不吸烟"},
                {"claim": "申请人养了一只狗", "label": "not_supported", "quote": "养狗"},
            ]
            required = {dim: "covered" for dim in cf.REQUIRED_DIMS}
        elif kind == "candidate_portrait":
            claims = [
                {"claim": "候选甲月租预算 4000 元", "label": "supported",
                 "quote": "月租预算：4000"},
            ]
            required = {"age": "covered", "budget": "covered"}
        elif kind == "run_summary":
            claims = [
                {"claim": "共调度 2 轮", "label": "supported", "quote": "调度 2 轮"},
                {"claim": "交付 1 人", "label": "contradicted", "quote": "交付 1 人"},
            ]
            required = {}
        else:
            claims = [
                {"claim": "否决原因是年龄必须项不满足", "label": "supported", "quote": "年龄"},
            ]
            required = {}
        outputs[material["item_id"]] = {"claims": claims, "required_dims": required}
    return outputs


class ContentFaithfulnessTest(unittest.TestCase):
    def setUp(self):
        self.bundle = make_bundle()
        self._original_call = cf._call_judge

    def tearDown(self):
        cf._call_judge = self._original_call

    def _inject_fake(self):
        cf._call_judge = lambda materials, env: fake_judge_outputs(materials)

    # -- 原文校验 ----------------------------------------------------------
    def test_quote_verification_normalization(self):
        source = "月租预算：4000 元。吸烟：不吸烟。"
        self.assertTrue(cf.quote_in_source("预算 4000 元", source))
        self.assertTrue(cf.quote_in_source("不吸烟", source))
        self.assertFalse(cf.quote_in_source("养狗", source))
        self.assertFalse(cf.quote_in_source("", source))
        self.assertEqual(cf.normalize_text("预算：4000 元"), "预算4000元")

    def test_quote_not_found_downgrades_to_not_supported(self):
        items = cf.build_items(self.bundle, limit_items=100)
        outputs = fake_judge_outputs(cf.build_judge_materials(items))
        payload = cf.evaluate(items, outputs)
        claims = [claim for item in payload["by_item"] for claim in item["claims"]]
        bogus = [claim for claim in claims if claim["claim"] == "申请人养了一只狗"]
        self.assertEqual(len(bogus), 1)
        self.assertEqual(bogus[0]["label"], "not_supported")
        self.assertFalse(bogus[0]["evidence_verified"])

    # -- 指标 --------------------------------------------------------------
    def test_metrics_rates_and_ci(self):
        items = cf.build_items(self.bundle, limit_items=100)
        self.assertEqual(len(items), 4)  # 申请人画像 + 运行摘要 + 交付候选画像 + 否决理由
        self.assertEqual({item["kind"] for item in items},
                         {"applicant_portrait", "run_summary",
                          "candidate_portrait", "reject_reason"})
        payload = cf.evaluate(items, fake_judge_outputs(cf.build_judge_materials(items)))
        self.assertEqual(payload["n_items"], 4)
        self.assertEqual(payload["n_claims"], 7)
        self.assertEqual(payload["supported"], 4)
        self.assertEqual(payload["contradicted"], 2)
        self.assertEqual(payload["not_supported"], 1)
        self.assertAlmostEqual(payload["faithful_rate"], round(4 / 7, 4))
        self.assertAlmostEqual(payload["contradiction_rate"], round(2 / 7, 4))
        self.assertAlmostEqual(payload["evidence_coverage"], round(6 / 7, 4))
        self.assertAlmostEqual(payload["required_dim_coverage"], 0.5)
        ci = payload["faithful_ci95"]
        self.assertEqual(ci["method"], "clopper-pearson")
        self.assertLessEqual(ci["lo"], ci["mean"])
        self.assertGreaterEqual(ci["hi"], ci["mean"])
        self.assertLessEqual(ci["lo"], payload["faithful_rate"])
        self.assertGreaterEqual(ci["hi"], payload["faithful_rate"])
        self.assertEqual(payload["protocol"], quality_spec.PROTOCOL_VERSION)
        self.assertEqual(payload["judge_version"], quality_spec.JUDGE_VERSION)

    def test_required_dim_coverage_only_counts_portraits(self):
        items = cf.build_items(self.bundle, limit_items=100)
        outputs = fake_judge_outputs(cf.build_judge_materials(items))
        # 只覆盖部分维度的候选画像不算齐全；运行摘要/否决理由不参与分母
        payload = cf.evaluate(items, outputs)
        self.assertAlmostEqual(payload["required_dim_coverage"], 0.5)
        candidate = [item for item in payload["by_item"]
                     if item["kind"] == "candidate_portrait"][0]
        self.assertEqual(len(candidate["missing_required_dims"]), 5)
        self.assertFalse(candidate["required_dim_complete"])
        summary = [item for item in payload["by_item"] if item["kind"] == "run_summary"][0]
        self.assertIsNone(summary["required_dim_complete"])

    def test_required_dim_coverage_none_without_portraits(self):
        bundle = make_bundle()
        bundle["runs"][0]["applicant"]["portrait"] = None
        bundle["runs"][0]["candidates"][0]["portrait"] = None
        items = cf.build_items(bundle, limit_items=100)
        self.assertEqual([item["kind"] for item in items], ["run_summary", "reject_reason"])
        payload = cf.evaluate(items, fake_judge_outputs(cf.build_judge_materials(items)))
        self.assertIsNone(payload["required_dim_coverage"])

    # -- 确定性规则 --------------------------------------------------------
    def test_deterministic_rule_warnings(self):
        items = cf.build_items(self.bundle, limit_items=100)
        warnings = cf.rule_warnings(items)
        dims = {(warning["item_id"], warning["dim"]) for warning in warnings}
        self.assertEqual(len(warnings), 2)
        candidate_item = [item for item in items if item["kind"] == "candidate_portrait"][0]
        self.assertIn((candidate_item["item_id"], "pet"), dims)
        self.assertIn((candidate_item["item_id"], "budget"), dims)

    def test_rule_warnings_clean_portrait(self):
        items = cf.build_items(self.bundle, limit_items=100)
        applicant_item = [item for item in items if item["kind"] == "applicant_portrait"][0]
        warnings = [warning for warning in cf.rule_warnings([applicant_item])]
        self.assertEqual(warnings, [])

    def test_rule_warnings_smoking_and_store(self):
        profile = {"smoking": "不吸烟", "store_id": 1, "rent_budget": 4000,
                   "lease_term": "3个月以下"}
        text = "我每天都抽烟，预算 4000 元，租期 6-12个月，想住金桥店。"
        warnings = cf._rule_warnings_for(profile, text, "X:1")
        dims = {warning["dim"] for warning in warnings}
        self.assertIn("smoking", dims)
        self.assertIn("lease", dims)
        self.assertIn("store", dims)
        self.assertNotIn("budget", dims)

    # -- run / prompt 注入 -------------------------------------------------
    def test_run_with_injected_judge(self):
        self._inject_fake()
        payload = cf.run(self.bundle, limit_items=100)
        self.assertTrue(payload["usable"])
        self.assertEqual(payload["rule_warnings"], 2)
        self.assertEqual(payload["judge_errors"], 0)
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["metric"], "content_faithfulness")
        # 材料白名单：发给 judge 的 item 只带内容与原文
        materials = cf.build_judge_materials(cf.build_items(self.bundle, limit_items=100))
        for material in materials:
            self.assertEqual(set(material), {"item_id", "kind", "content", "source_text"})
            cf.assert_safe_material(material)

    def test_run_judge_error_marks_unusable(self):
        def broken(materials, env):
            raise RuntimeError("网络抖动")

        cf._call_judge = broken
        payload = cf.run(self.bundle, limit_items=100)
        self.assertFalse(payload["usable"])
        self.assertTrue(any("judge 调用失败" in reason for reason in payload["reasons"]))

    def test_run_partial_missing_output_marks_unusable(self):
        self._inject_fake()
        real_judge = cf._call_judge
        items = cf.build_items(self.bundle, limit_items=100)

        def partial(materials, env):
            outputs = real_judge(materials, env)
            for item_id in list(outputs)[:2]:
                outputs.pop(item_id)
            return outputs

        cf._call_judge = partial
        payload = cf.run(self.bundle, limit_items=100)
        self.assertEqual(payload["judge_errors"], 2)
        self.assertFalse(payload["usable"])
        self.assertEqual(len(items), 4)

    def test_empty_bundle_unusable(self):
        payload = cf.run({"runs": []}, limit_items=10)
        self.assertEqual(payload["n_items"], 0)
        self.assertEqual(payload["n_claims"], 0)
        self.assertFalse(payload["usable"])

    # -- 抽样 --------------------------------------------------------------
    def test_sampling_deterministic_and_limited(self):
        first = cf.build_items(self.bundle, limit_items=2)
        second = cf.build_items(self.bundle, limit_items=2)
        self.assertEqual([item["item_id"] for item in first],
                         [item["item_id"] for item in second])
        self.assertEqual(len(first), 2)
        full = {item["item_id"] for item in cf.build_items(self.bundle, limit_items=100)}
        self.assertTrue({item["item_id"] for item in first} <= full)

    # -- CLI（离线） -------------------------------------------------------
    def test_cli_dry_run_offline(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle_path = tmp / "bundle.json"
            bundle_path.write_text(json.dumps(self.bundle, ensure_ascii=False),
                                   encoding="utf-8")
            out = tmp / "out.json"
            sample = tmp / "claims.csv"
            code = cf.main([
                "--bundle", str(bundle_path), "--out", str(out),
                "--limit-items", "20", "--dry-run",
                "--emit-human-sample", str(sample),
                "--env-file", str(tmp / "missing.env"),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["usable"])
            self.assertEqual(payload["n_claims"], 0)
            self.assertEqual(payload["rule_warnings"], 2)
            self.assertTrue(payload["reasons"])
            with sample.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames), cf.HUMAN_SAMPLE_COLUMNS)
                self.assertEqual(list(reader), [])

    def test_cli_fake_json_offline(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle_path = tmp / "bundle.json"
            bundle_path.write_text(json.dumps(self.bundle, ensure_ascii=False),
                                   encoding="utf-8")
            items = cf.build_items(self.bundle, limit_items=100)
            fake = fake_judge_outputs(cf.build_judge_materials(items))
            fake_path = tmp / "fake.json"
            fake_path.write_text(json.dumps({"items": [
                dict(value, item_id=key) for key, value in fake.items()]},
                ensure_ascii=False), encoding="utf-8")
            out = tmp / "out.json"
            sample = tmp / "claims.csv"
            code = cf.main([
                "--bundle", str(bundle_path), "--out", str(out),
                "--fake-json", str(fake_path),
                "--emit-human-sample", str(sample),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["usable"])
            self.assertEqual(payload["n_claims"], 7)
            self.assertAlmostEqual(payload["faithful_rate"], round(4 / 7, 4))
            with sample.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 7)
            self.assertEqual(tuple(rows[0]), cf.HUMAN_SAMPLE_COLUMNS)
            self.assertTrue(all(row["judge_label"] in cf.LABELS for row in rows))
            self.assertTrue(any(row["judge_quote"] for row in rows))
            self.assertTrue(any(row["source_excerpt"] for row in rows))

    # -- 材料白名单 --------------------------------------------------------
    def test_assert_safe_material_rejects_system_metadata(self):
        with self.assertRaises(ValueError):
            cf.assert_safe_material({"item_id": "x", "delivered": True})
        with self.assertRaises(ValueError):
            cf.assert_safe_material({"item_id": "x", "candidate": {"screen_score": 1.0}})
        cf.assert_safe_material({"item_id": "x", "content": "c",
                                 "source_text": "s"})


if __name__ == "__main__":
    unittest.main()
