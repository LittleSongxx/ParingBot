#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审核误拒率 / 假通过率离线测试：不联网、不读 .env、不依赖 backend。

覆盖：
- 硬规则 replay（同性 / 双向必须项 / 租期档差）与 hard false reject 判定；
- 假通过（通过候选存在硬违规）检测；
- 软冲突三分类 judge 注入、误拒率、--limit 确定性抽样；
- 未分类否决不计入 hard.rate；软冲突否决 replay 出硬违规时记为分类不一致；
- --dry-run / --fake-json 离线 CLI、人工校准 CSV、材料白名单、usable 门禁。
"""
import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import false_reject as fr  # noqa: E402
import quality_spec  # noqa: E402


# ---------------------------------------------------------------------------
# 合成 bundle
# ---------------------------------------------------------------------------
def _person(member_id: int, nickname: str, gender: str = "女",
            birth: str = "1995-01-01 00:00:00", lease: str = "3-6个月",
            preference: dict | None = None, **extra) -> dict:
    person = {
        "id": member_id,
        "nickname": nickname,
        "gender": gender,
        "birth_date": birth,
        "rent_budget": 3000,
        "tidiness": "一般",
        "occupation": "财务",
        "lease_term": lease,
        "store_id": 1,
        "schedule_type": "正常作息",
        "has_pet": "无",
        "smoking": "不吸烟",
        "self_intro": f"{nickname}的自我介绍。",
        "roommate_expectation": "希望安静。",
        "interest_tags": "电影,徒步",
        "preference": preference or {},
        "portrait": {"summary": f"{nickname}的画像 summary", "lifestyle_tags": "作息规律"},
        "moments": [{"content": "今天下班很早。", "time": "2026-11-01 10:00:00"}],
    }
    person.update(extra)
    return person


def _candidate(member_id: int, nickname: str, audit_status: str,
               reject_code=None, reject_reason=None, **extra) -> dict:
    base = _person(member_id, nickname, **extra)
    base.update({
        "delivered": audit_status == "通过" and bool(extra.pop("delivered", False)),
        "audit_status": audit_status,
        "reject_code": reject_code,
        "reject_reason": reject_reason,
    })
    return base


def make_bundle() -> dict:
    applicant = _person(
        100, "申请方甲", preference={},
        username="TEST_T6_FR")
    applicant["preference"] = {
        "age_required": "加分", "budget_required": "加分", "tidiness_required": "加分",
        "store_required": "加分", "schedule_required": "加分", "lease_required": "加分",
        "pet_required": "加分",
    }
    # A：候选方年龄必须 40-50，申请方 31 岁 → 硬违规，否决正确
    age_hard = {"age_required": "必须", "age_min": 40, "age_max": 50}
    # B：候选方年龄必须 25-40，申请方 31 岁 → 无硬违规，但仍被按硬冲突否决 → 硬误拒
    age_ok = {"age_required": "必须", "age_min": 25, "age_max": 40}
    candidates = [
        _candidate(201, "候选A", "否决", "MISMATCH_HARD",
                   "申请方不满足候选方标为必须的条件：年龄",
                   preference=age_hard),
        _candidate(202, "候选B", "否决", "MISMATCH_HARD",
                   "申请方不满足候选方标为必须的条件：年龄",
                   preference=age_ok),
        _candidate(203, "候选C", "否决", "PREFERENCE_CONFLICT",
                   "双方作息习惯冲突", preference={}),
        _candidate(204, "候选D", "否决", "PORTRAIT_INSUFFICIENT",
                   "缺作息：几点睡、几点起都没有依据", preference={}),
        _candidate(205, "候选E", "否决", "PREFERENCE_CONFLICT",
                   "整洁度习惯冲突", preference={}),
        _candidate(206, "候选F", "通过", delivered=True,
                   gender="男", preference={}),
        _candidate(207, "候选G", "通过", delivered=True, preference={}),
        _candidate(208, "候选H", "否决", None, "未分类否决",
                   preference={}),
    ]
    return {
        "generated_at": "2026-11-06 10:00:00",
        "meta": {"generated_at": "2026-11-06 10:00:00", "code_commit": "test-bundle"},
        "runs": [{
            "run": {"id": 1, "run_no": "MATCH-TEST-FR", "status": "已完成", "total_round": 2,
                    "summary": "调度 2 轮"},
            "task": {"id": 1, "deliver_count": 2},
            "applicant": applicant,
            "deliverable_passed_count": 2,
            "delivered_to_user": 2,
            "candidates": candidates,
            "rounds": [],
            "funnel": {"stages": []},
        }],
    }


def fake_soft_judge(materials: list[dict]) -> dict:
    outputs = {}
    for material in materials:
        item_id = material["item_id"]
        code = material["reject_code"]
        if code == "PREFERENCE_CONFLICT":
            label = "should_pass" if item_id.endswith("R203") else "needs_info"
        else:
            label = "reasonable_reject"
        outputs[item_id] = {"label": label, "reason": "测试标签"}
    return outputs


class FalseRejectTest(unittest.TestCase):
    def setUp(self):
        self.bundle = make_bundle()
        self._original_call = fr._call_judge

    def tearDown(self):
        fr._call_judge = self._original_call

    def _inject_fake(self):
        fr._call_judge = lambda materials, env: fake_soft_judge(materials)

    def _sampled_soft_materials(self):
        replay = fr.replay(self.bundle)
        soft_rows = [row for row in replay["rejected"] if row["code"] in fr.SOFT_CODES]
        return fr.build_judge_materials(fr.sample_rows(soft_rows, 100))

    # -- 硬规则 replay -----------------------------------------------------
    def test_replay_hard_rules(self):
        result = fr.replay(self.bundle)
        self.assertEqual(result["as_of"], "2026-11-06")
        self.assertEqual(len(result["rejected"]), 6)
        self.assertEqual(len(result["passed"]), 2)
        by_id = {row["candidate_id"]: row for row in result["rejected"]}
        self.assertEqual(by_id[201]["violations"], ["年龄"])
        self.assertTrue(by_id[201]["hard_violation"])
        self.assertEqual(by_id[202]["violations"], [])
        self.assertFalse(by_id[202]["hard_violation"])
        passed_by_id = {row["candidate_id"]: row for row in result["passed"]}
        self.assertEqual(passed_by_id[206]["violations"], ["性别"])
        self.assertEqual(passed_by_id[207]["violations"], [])

    def test_replay_lease_gap_and_same_gender(self):
        bundle = copy.deepcopy(self.bundle)
        # 申请方 3-6个月 vs 候选方 2年以上：档位差 >= 2，属硬冲突
        bundle["runs"][0]["applicant"]["lease_term"] = "3个月以下"
        bundle["runs"][0]["candidates"][2]["lease_term"] = "2年以上"
        result = fr.replay(bundle)
        row = [item for item in result["rejected"] if item["candidate_id"] == 203][0]
        self.assertIn("租期", row["violations"])
        # 同性：女 + 女 → 无性别冲突；改成男 → 性别冲突
        bundle["runs"][0]["applicant"]["gender"] = "女"
        bundle["runs"][0]["candidates"][2]["gender"] = "男"
        row = [item for item in fr.replay(bundle)["rejected"]
               if item["candidate_id"] == 203][0]
        self.assertIn("性别", row["violations"])

    def test_preference_strings_like_real_bundle(self):
        bundle = copy.deepcopy(self.bundle)
        candidate = bundle["runs"][0]["candidates"][2]
        candidate["preference"] = {
            "age_min": "40", "age_max": "50", "age_required": "必须",
            "budget_min": "None", "budget_max": "None", "budget_required": "加分",
            "tidiness_min": "None", "lease_min": "None", "schedule_accept": "",
            "store_scope": "不限", "pet_accept": "无所谓",
        }
        row = [item for item in fr.replay(bundle)["rejected"]
               if item["candidate_id"] == 203][0]
        self.assertEqual(row["violations"], ["年龄"])

    # -- 指标 --------------------------------------------------------------
    def test_metrics_with_fake_judge(self):
        self._inject_fake()
        payload = fr.run(self.bundle, limit=100)
        self.assertEqual(payload["metric"], "false_reject")
        self.assertEqual(payload["protocol"], quality_spec.PROTOCOL_VERSION)
        self.assertEqual(payload["judge_version"], quality_spec.JUDGE_VERSION)
        hard = payload["hard"]
        self.assertEqual(hard["n"], 2)             # A、B 按硬冲突否决
        self.assertEqual(hard["false_reject"], 1)  # B 无硬违规
        self.assertAlmostEqual(hard["rate"], 0.5)
        self.assertEqual(hard["by_code"]["MISMATCH_HARD"]["n"], 2)
        self.assertEqual(hard["by_code"]["MISMATCH_HARD"]["false_reject"], 1)
        self.assertEqual(hard["ci95"]["method"], "clopper-pearson")
        soft = payload["soft"]
        self.assertEqual(soft["n"], 3)             # C/D/E
        self.assertEqual(soft["should_pass"], 1)
        self.assertEqual(soft["needs_info"], 1)
        self.assertEqual(soft["reasonable_reject"], 1)
        self.assertAlmostEqual(soft["rate"], round(1 / 3, 4))
        self.assertEqual(soft["false_reject"], soft["should_pass"])
        false_pass = payload["false_pass"]
        self.assertEqual(false_pass["n"], 2)       # F、G
        self.assertEqual(false_pass["count"], 1)   # F 性别不同却通过
        self.assertAlmostEqual(false_pass["rate"], 0.5)
        self.assertEqual(false_pass["items"][0]["violations"], ["性别"])
        self.assertTrue(payload["usable"])
        totals = payload["totals"]
        self.assertEqual(totals["rejected"], 6)
        self.assertEqual(totals["passed"], 2)
        self.assertEqual(totals["hard_replay"], 2)
        self.assertEqual(totals["soft_replay"], 3)
        self.assertEqual(totals["other_rejected"], 1)
        self.assertEqual(payload["reject_code_counts"]["UNCODED"], 1)
        scenario = payload["by_scenario"][0]
        self.assertEqual(scenario["scenario"], "TEST_T6_FR")
        self.assertEqual(scenario["rejects"], 6)
        self.assertEqual(scenario["hard_false_reject"], 1)
        self.assertEqual(scenario["soft_should_pass"], 1)
        self.assertEqual(scenario["false_pass"], 1)

    def test_judge_error_marks_unusable(self):
        def broken(materials, env):
            raise RuntimeError("judge 挂了")

        fr._call_judge = broken
        payload = fr.run(self.bundle, limit=100)
        self.assertFalse(payload["usable"])
        self.assertEqual(payload["soft"]["n"], 0)
        self.assertTrue(any("judge 调用失败" in reason for reason in payload["reasons"]))
        # 硬规则 / 假通过仍应产出
        self.assertAlmostEqual(payload["hard"]["rate"], 0.5)
        self.assertEqual(payload["false_pass"]["count"], 1)

    def test_dry_run_offline_never_calls_judge(self):
        def should_not_call(materials, env):
            raise AssertionError("dry-run 不应调用 judge")

        fr._call_judge = should_not_call
        payload = fr.run(self.bundle, dry_run=True)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["usable"])
        self.assertEqual(payload["soft"]["n"], 0)
        self.assertAlmostEqual(payload["hard"]["rate"], 0.5)
        self.assertEqual(payload["false_pass"]["count"], 1)
        self.assertTrue(any("dry-run" in reason for reason in payload["reasons"]))

    def test_limit_is_deterministic(self):
        items_seen = []

        def recorder(materials, env):
            items_seen.append([material["item_id"] for material in materials])
            return {material["item_id"]: {"label": "should_pass", "reason": "r"}
                    for material in materials}

        fr._call_judge = recorder
        first = fr.run(self.bundle, limit=1)
        second = fr.run(self.bundle, limit=1)
        self.assertEqual(first["soft"]["sampled"], 1)
        self.assertEqual(first["soft"]["n"], 1)
        self.assertEqual(len(items_seen), 2)
        self.assertEqual(items_seen[0], items_seen[1])
        self.assertEqual(second["soft"]["should_pass"], 1)

    def test_uncoded_reject_excluded_from_hard_rate(self):
        replay = fr.replay(self.bundle)
        uncoded = [row for row in replay["rejected"] if row["code"] == "UNCODED"]
        self.assertEqual(len(uncoded), 1)
        self._inject_fake()
        payload = fr.run(self.bundle, limit=100)
        self.assertTrue(any("未计入 hard.rate" in reason for reason in payload["reasons"]))

    def test_soft_code_with_hard_violation_counts_as_mismatch(self):
        bundle = copy.deepcopy(self.bundle)
        candidate = bundle["runs"][0]["candidates"][2]
        candidate["reject_code"] = "PREFERENCE_CONFLICT"
        candidate["preference"] = {"age_required": "必须", "age_min": 40, "age_max": 50}
        self._inject_fake()
        payload = fr.run(bundle, limit=100)
        self.assertEqual(payload["code_mismatch"]["soft_with_hard_violation"], 1)
        self.assertTrue(any("分类错误" in reason for reason in payload["reasons"]))
        # 分类不一致不影响软误拒统计（soft 仍按 judge 结果）
        self.assertEqual(payload["soft"]["n"], 3)

    def test_no_audited_candidates_unusable(self):
        bundle = copy.deepcopy(self.bundle)
        for candidate in bundle["runs"][0]["candidates"]:
            candidate["audit_status"] = "待审核"
        payload = fr.run(bundle, dry_run=True)
        self.assertFalse(payload["usable"])
        self.assertEqual(payload["totals"]["rejected"], 0)
        self.assertEqual(payload["totals"]["passed"], 0)

    # -- 材料白名单 --------------------------------------------------------
    def test_materials_whitelist(self):
        materials = self._sampled_soft_materials()
        self.assertEqual(len(materials), 3)
        for material in materials:
            self.assertIn("reject_code", material)
            self.assertIn("reject_reason", material)
            fr.assert_safe_material(material)
            serialized = json.dumps(material, ensure_ascii=False)
            self.assertNotIn("audit_status", serialized)
            self.assertNotIn("delivered", serialized)
        with self.assertRaises(ValueError):
            fr.assert_safe_material({"item_id": "x", "delivered": True})
        with self.assertRaises(ValueError):
            fr.assert_safe_material({"item_id": "x", "candidate": {"screen_score": 1.0}})
        with self.assertRaises(ValueError):
            fr.assert_safe_material({"item_id": "x", "audit_status": "通过"})

    # -- CLI（离线） -------------------------------------------------------
    def test_cli_dry_run_offline(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle_path = tmp / "bundle.json"
            bundle_path.write_text(json.dumps(self.bundle, ensure_ascii=False),
                                   encoding="utf-8")
            out = tmp / "out.json"
            sample = tmp / "soft.csv"
            code = fr.main([
                "--bundle", str(bundle_path), "--out", str(out),
                "--dry-run", "--emit-human-sample", str(sample),
                "--env-file", str(tmp / "missing.env"),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["usable"])
            self.assertAlmostEqual(payload["hard"]["rate"], 0.5)
            self.assertEqual(payload["false_pass"]["count"], 1)
            self.assertEqual(payload["soft"]["n"], 0)
            with sample.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames), fr.HUMAN_SAMPLE_COLUMNS)
                self.assertEqual(list(reader), [])

    def test_cli_fake_json_offline(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            bundle_path = tmp / "bundle.json"
            bundle_path.write_text(json.dumps(self.bundle, ensure_ascii=False),
                                   encoding="utf-8")
            fake = fake_soft_judge(self._sampled_soft_materials())
            fake_path = tmp / "fake.json"
            fake_path.write_text(json.dumps({"items": [
                dict(value, item_id=key) for key, value in fake.items()]},
                ensure_ascii=False), encoding="utf-8")
            out = tmp / "out.json"
            sample = tmp / "soft.csv"
            code = fr.main([
                "--bundle", str(bundle_path), "--out", str(out),
                "--fake-json", str(fake_path),
                "--emit-human-sample", str(sample),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["soft"]["n"], 3)
            self.assertAlmostEqual(payload["soft"]["rate"], round(1 / 3, 4))
            self.assertTrue(payload["usable"])
            with sample.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual(tuple(rows[0]), fr.HUMAN_SAMPLE_COLUMNS)
            labels = {row["judge_label"] for row in rows}
            self.assertEqual(labels, {"should_pass", "needs_info", "reasonable_reject"})


if __name__ == "__main__":
    unittest.main()
