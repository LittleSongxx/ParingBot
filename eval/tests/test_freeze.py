#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 冻结场景/标签/MANIFEST/check_freeze 的单测（离线，不需要 DB / 模型）。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
REPO = EVAL_DIR.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.lib import rules, seed as seedmod  # noqa: E402


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load_module("v3_scenarios_builder", "build_v3_scenarios.py")
labels_mod = _load_module("v3_labels_builder", "build_frozen_labels.py")
freeze = _load_module("v3_check_freeze", "check_freeze.py")

AS_OF = build.AS_OF


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FrozenSuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = seedmod.load_seed(REPO)
        cls.pool = seedmod.approved_candidates(cls.seed)
        cls.scenarios_data = build.build_scenarios(REPO)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.tmpdir = Path(cls.tmp.name)
        cls.scenarios_path = build.write_scenarios(cls.scenarios_data, cls.tmpdir)
        result = labels_mod.generate(cls.tmpdir, REPO, write=True)
        cls.labels_data = result["labels"]
        cls.manifest = result["manifest"]
        cls.labels_path = cls.tmpdir / "labels.json"
        cls.manifest_path = cls.tmpdir / "MANIFEST.json"
        cls.positives = [item for item in cls.scenarios_data["scenarios"] if item["run"]]
        cls.negatives = [item for item in cls.scenarios_data["scenarios"] if not item["run"]]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---------------- 场景结构 ----------------
    def test_scenario_counts_and_accounts(self):
        data = self.scenarios_data
        self.assertEqual(data["scenario_count"], 10)
        self.assertEqual(data["positive_count"], 8)
        self.assertEqual(data["negative_count"], 2)
        self.assertEqual(data["deliver_count"], 8)
        self.assertEqual(data["seed"], 20261104)
        self.assertEqual(data["as_of"], "2026-11-04")
        self.assertEqual(len(data["scenarios"]), 10)
        for index, scenario in enumerate(data["scenarios"], 1):
            self.assertEqual(scenario["key"], f"V3_{index:02d}")
            self.assertEqual(scenario["account"], f"TEST_SCENARIO_V3_{index:02d}")
            self.assertEqual(scenario["deliver_count"], 8)
            for name in ("title", "profile", "preference", "moments", "expect", "why",
                         "ex_ante_capacity"):
                self.assertIn(name, scenario)
        self.assertEqual([item["key"] for item in self.positives],
                         [f"V3_{index:02d}" for index in range(1, 9)])
        self.assertEqual([item["key"] for item in self.negatives], ["V3_09", "V3_10"])

    def test_scenarios_are_deterministic(self):
        first = build.dump_scenarios(build.build_scenarios(REPO))
        second = build.dump_scenarios(build.build_scenarios(REPO))
        self.assertEqual(first, second)
        self.assertEqual(first, self.scenarios_path.read_text(encoding="utf-8"))
        labels_one = labels_mod.dump_labels(labels_mod.build_labels(self.scenarios_data, REPO))
        labels_two = labels_mod.dump_labels(labels_mod.build_labels(self.scenarios_data, REPO))
        self.assertEqual(labels_one, labels_two)
        self.assertEqual(labels_one, self.labels_path.read_text(encoding="utf-8"))

    def test_capacity_tiers(self):
        tiers = [item["ex_ante_capacity"]["tier"] for item in self.positives]
        self.assertEqual(tiers.count("high"), 3)
        self.assertEqual(tiers.count("medium"), 3)
        self.assertEqual(tiers.count("low"), 2)
        for item in self.positives:
            capacity = item["ex_ante_capacity"]
            eligible = capacity["eligible"]
            self.assertGreaterEqual(eligible, 1)
            if capacity["tier"] == "high":
                self.assertGreaterEqual(eligible, 8)
            elif capacity["tier"] == "medium":
                self.assertTrue(4 <= eligible <= 7, eligible)
            else:
                self.assertTrue(1 <= eligible <= 3, eligible)
            self.assertGreaterEqual(capacity["eligible_unbounded"], eligible)
            self.assertIn(capacity["store_scope"], ("同门店", "同片区", "不限"))
            self.assertEqual(capacity["requested"], 8)

    def test_must_plan_matches_protocol(self):
        store_must = [item for item in self.positives
                      if "store" in item["ex_ante_capacity"]["must_codes"]]
        budget_must = [item for item in self.positives
                       if "budget" in item["ex_ante_capacity"]["must_codes"]]
        pet_must = [item for item in self.positives
                    if "pet" in item["ex_ante_capacity"]["must_codes"]]
        self.assertEqual(len(store_must), 2)
        self.assertEqual(len(budget_must), 2)
        self.assertEqual(len(pet_must), 1)
        for item in self.positives:
            preference = item["preference"]
            self.assertEqual(preference["age_required"], "必须")
            self.assertEqual(preference["schedule_required"], "必须")
            must_count = len([name for name in (
                "age_required", "budget_required", "tidiness_required", "store_required",
                "schedule_required", "lease_required", "pet_required",
            ) if preference[name] == "必须"])
            self.assertGreaterEqual(must_count, 2)  # 业务校验：必须项 2-4 个
            self.assertLessEqual(must_count, 4)

    def test_diversity_constraints(self):
        stores = {item["ex_ante_capacity"]["store_id"] for item in self.positives}
        genders = [item["profile"]["gender"] for item in self.positives]
        leases = {item["profile"]["lease_term"] for item in self.positives}
        self.assertEqual(len(stores), 8)
        self.assertEqual(genders.count("男"), 4)
        self.assertEqual(genders.count("女"), 4)
        self.assertGreaterEqual(len(leases), 4)
        for item in self.positives:
            self.assertIs(item["run"], True)
        for item in self.negatives:
            self.assertIs(item["run"], False)

    def test_no_copied_seed_text(self):
        seed_texts = set()
        for member in self.seed.members:
            if member.self_intro:
                seed_texts.add(member.self_intro.strip())
            if member.roommate_expectation:
                seed_texts.add(member.roommate_expectation.strip())
        intros = []
        expectations = []
        for scenario in self.scenarios_data["scenarios"]:
            profile = scenario["profile"]
            intro = profile["self_intro"].strip()
            expectation = profile["roommate_expectation"].strip()
            if intro:
                self.assertNotIn(intro, seed_texts, scenario["key"])
                intros.append(intro)
            if expectation:
                self.assertNotIn(expectation, seed_texts, scenario["key"])
                expectations.append(expectation)
        self.assertEqual(len(intros), len(set(intros)))
        self.assertEqual(len(expectations), len(set(expectations)))

    def test_profile_payload_values_are_valid(self):
        tag_pattern = re.compile(r"INSERT INTO `interest_tag` VALUES \(\d+, '([^']+)'")
        sql_text = seedmod.seed_sql_path(REPO).read_text(encoding="utf-8", errors="replace")
        tag_vocab = set(tag_pattern.findall(sql_text))
        self.assertGreater(len(tag_vocab), 50)
        nicknames = set()
        for scenario in self.scenarios_data["scenarios"]:
            profile = scenario["profile"]
            preference = scenario["preference"]
            self.assertIn(profile["gender"], ("男", "女"))
            self.assertIn(profile["tidiness"], rules.TIDINESS_LEVELS)
            self.assertIn(profile["lease_term"], rules.LEASE_TERMS)
            self.assertIn(profile["schedule_type"], rules.SCHEDULE_TYPES)
            self.assertIn(profile["has_pet"], ("有", "无"))
            self.assertIn(profile["smoking"], ("不吸烟", "偶尔", "经常"))
            self.assertTrue(1 <= int(profile["store_id"]) <= 20)
            age = rules.age_of(date.fromisoformat(profile["birth_date"]), AS_OF)
            self.assertTrue(18 <= age <= 80, (scenario["key"], age))
            self.assertTrue(profile["nickname"])
            nicknames.add(profile["nickname"])
            self.assertTrue(profile["interest_tags"])
            self.assertTrue(set(profile["interest_tags"]) <= tag_vocab,
                            (scenario["key"], profile["interest_tags"]))
            self.assertIn(preference["age_required"], ("必须", "加分"))
            self.assertIn(preference["budget_required"], ("必须", "加分"))
            self.assertIn(preference["store_scope"], ("同门店", "同片区", "不限"))
            self.assertIn(preference["pet_accept"], ("接受", "不接受", "无所谓"))
            self.assertTrue(preference["schedule_accept"])
            self.assertTrue(set(preference["schedule_accept"]) <= set(rules.SCHEDULE_TYPES))
            self.assertTrue(800 <= preference["budget_min"] <= preference["budget_max"] <= 20000)
            self.assertTrue(18 <= preference["age_min"] <= preference["age_max"] <= 80)
            self.assertIn(preference["tidiness_min"],
                          list(rules.TIDINESS_LEVELS) + ["不限"])
            self.assertIn(preference["lease_min"], list(rules.LEASE_TERMS) + ["不限"])
        self.assertEqual(len(nicknames), len(self.scenarios_data["scenarios"]))

    def test_negative_scenarios(self):
        by_key = {item["key"]: item for item in self.scenarios_data["scenarios"]}
        moment_case = by_key["V3_09"]
        self.assertEqual(moment_case["expect"]["blocker"], "moment")
        self.assertIs(moment_case["expect"]["can_run"], False)
        self.assertEqual(moment_case["moments"], [])
        self.assertTrue(moment_case["profile"]["self_intro"])
        intro_case = by_key["V3_10"]
        self.assertEqual(intro_case["expect"]["blocker"], "intro")
        self.assertIs(intro_case["expect"]["can_run"], False)
        self.assertEqual(intro_case["profile"]["self_intro"], "")
        self.assertTrue(intro_case["moments"])
        self.assertIn("必填", intro_case["expect"]["note"])

    # ---------------- 冻结标签 ----------------
    def test_labels_alignment(self):
        labels = self.labels_data["labels"]
        self.assertEqual(len(labels), len(self.positives))
        by_key = {item["key"]: item for item in labels}
        self.assertEqual(set(by_key), {item["key"] for item in self.positives})
        for scenario in self.positives:
            label = by_key[scenario["key"]]
            ranked = label["ranked"]
            self.assertEqual(label["username"], scenario["account"])
            self.assertEqual(label["hard_eligible"], len(ranked))
            self.assertLessEqual(len(label["gold_ids"]), 8)
            self.assertEqual(label["gold_ids"], [item["id"] for item in ranked[:8]])
            self.assertEqual(label["ranked_total"], len(ranked))
            self.assertEqual(label["ex_ante_capacity"], scenario["ex_ante_capacity"])
            self.assertGreaterEqual(label["hard_eligible"],
                                    scenario["ex_ante_capacity"]["eligible"])
            for index in range(len(ranked) - 1):
                left, right = ranked[index], ranked[index + 1]
                self.assertGreaterEqual(left["score"], right["score"])
                if left["score"] == right["score"]:
                    self.assertLess(left["id"], right["id"])

    def test_labels_are_hard_eligible_only(self):
        pool_by_id = {member.id: member for member in self.pool}
        preferences = self.seed.preferences
        scenario_map = {item["key"]: item for item in self.positives}
        for label in self.labels_data["labels"]:
            scenario = scenario_map[label["key"]]
            applicant = seedmod.member_from_payload(scenario["profile"])
            applicant_pref = seedmod.preference_from_payload(scenario["preference"])
            for item in label["ranked"]:
                candidate = pool_by_id[item["id"]]
                self.assertTrue(rules.is_hard_eligible(
                    applicant, applicant_pref, candidate,
                    preferences[candidate.id], AS_OF),
                    (label["key"], candidate.id))

    def test_manifest_hashes(self):
        manifest = self.manifest
        self.assertEqual(manifest["supply_additions"], 0)
        self.assertEqual(manifest["seed"], self.scenarios_data["seed"])
        self.assertEqual(manifest["protocol_version"], self.scenarios_data["protocol_version"])
        scenarios_bytes = self.scenarios_path.read_bytes()
        labels_bytes = self.labels_path.read_bytes()
        self.assertEqual(manifest["scenarios"]["sha256"], _sha256_bytes(scenarios_bytes))
        self.assertEqual(manifest["labels"]["sha256"], _sha256_bytes(labels_bytes))
        self.assertEqual(manifest["pool"]["approved"], len(self.pool))
        self.assertIn("deploy/mysql/", manifest["pool"]["source"])
        self.assertTrue((self.manifest_path.read_text(encoding="utf-8")).strip())
        self.assertEqual(json.loads(self.manifest_path.read_text(encoding="utf-8")),
                         json.loads(labels_mod.dump_manifest(manifest)))

    def test_verify_passes_on_frozen_dir(self):
        self.assertEqual(labels_mod.verify(self.tmpdir, REPO), 0)
        self.assertEqual(freeze.check_manifest(self.tmpdir), [])

    def test_verify_detects_tampered_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("scenarios.json", "labels.json", "MANIFEST.json"):
                (base / name).write_bytes((self.tmpdir / name).read_bytes())
            payload = json.loads((base / "labels.json").read_text(encoding="utf-8"))
            payload["labels"][0]["gold_ids"] = payload["labels"][0]["gold_ids"][:-1]
            (base / "labels.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertNotEqual(labels_mod.verify(base, REPO), 0)
            self.assertTrue(freeze.check_manifest(base))

    def test_verify_detects_tampered_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("scenarios.json", "labels.json", "MANIFEST.json"):
                (base / name).write_bytes((self.tmpdir / name).read_bytes())
            data = json.loads((base / "scenarios.json").read_text(encoding="utf-8"))
            data["scenarios"][0]["title"] += "（改）"
            (base / "scenarios.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertNotEqual(labels_mod.verify(base, REPO), 0)
            self.assertTrue(freeze.check_manifest(base))

    # ---------------- 守卫 ----------------
    def test_manifest_requires_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = freeze.check_manifest(Path(tmp))
            self.assertEqual(len(errors), 3)

    def test_eval_sql_scan_blocks_supply(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql_dir = Path(tmp)
            (sql_dir / "README.md").write_text("eval profile 禁止供给\n", encoding="utf-8")
            self.assertEqual(freeze.scan_eval_sql(sql_dir), [])
            (sql_dir / "01-add.sql").write_text(
                "INSERT INTO `member_profile` VALUES (1, 2, 'x', '男');\n", encoding="utf-8")
            (sql_dir / "02-update.sql").write_text(
                "UPDATE roommate_preference SET age_min = 20 WHERE member_id = 1;\n",
                encoding="utf-8")
            (sql_dir / "03-comment.sql").write_text(
                "-- INSERT INTO member_profile VALUES (1);\n"
                "INSERT INTO `agent_definition` VALUES (9, 'X');\n", encoding="utf-8")
            violations = freeze.scan_eval_sql(sql_dir)
            self.assertEqual(len(violations), 2)
            joined = "\n".join(violations)
            self.assertIn("01-add.sql", joined)
            self.assertIn("02-update.sql", joined)
            self.assertNotIn("03-comment.sql", joined)

    def test_check_freeze_main_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "frozen"
            base.mkdir()
            for name in ("scenarios.json", "labels.json", "MANIFEST.json"):
                (base / name).write_bytes((self.tmpdir / name).read_bytes())
            sql_dir = Path(tmp) / "sql"
            sql_dir.mkdir()
            self.assertEqual(freeze.main(["--frozen-dir", str(base), "--sql-dir", str(sql_dir)]), 0)
            (sql_dir / "supply.sql").write_text(
                "INSERT INTO `member_profile` VALUES (1);\n", encoding="utf-8")
            self.assertEqual(freeze.main(["--frozen-dir", str(base), "--sql-dir", str(sql_dir)]), 1)
            (sql_dir / "supply.sql").unlink()
            (base / "labels.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(freeze.main(["--frozen-dir", str(base), "--sql-dir", str(sql_dir)]), 1)

    def test_repo_frozen_artifacts_consistent(self):
        """仓库里已提交的 v3 冻结产物必须自洽（CI 的 freeze-guard 依赖这一点）。"""
        self.assertEqual(freeze.main([]), 0)
        self.assertEqual(labels_mod.verify(None, REPO), 0)
        frozen_dir = EVAL_DIR / "frozen" / "v3"
        committed = json.loads((frozen_dir / "scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["seed"], 20261104)
        self.assertEqual(len(committed["scenarios"]), 10)


if __name__ == "__main__":
    unittest.main()