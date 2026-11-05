#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 冻结场景 / MANIFEST / 标签工具的单测（离线，不需要 DB / 模型）。

覆盖（审计 A4 修复点）：
- v4 build 形状/确定性/frozen 字节一致；slot=seq 与昵称唯一（不再有“第 208 次”）；
- 清洗后兴趣标签与 self_intro/moments 文本自洽（无“养猫撸猫 vs 不养宠物”）；
- expect.target=min(8, eligible_unbounded) 与容量层配额；
- 负向 8 个来自固定索引且跨层跨性别；
- MANIFEST sha256 / protocol / pool 指纹可复现；--check 只读且能发现篡改；
- v3 冻结 scenarios 字节不变（v3 生成器只加 opt-in 参数）；
- build_v4_labels 的 CSV/judge 输入、schema、覆盖 40 正向与 MANIFEST 更新。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
REPO = EVAL_DIR.parent
for _path in (str(REPO), str(EVAL_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
HUMAN_EVAL_DIR = EVAL_DIR / "human_eval"
if str(HUMAN_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(HUMAN_EVAL_DIR))

import build_v3_scenarios as v3  # noqa: E402
import build_v4_labels as v4labels  # noqa: E402
import build_v4_scenarios as v4  # noqa: E402
import check_v4_freeze  # noqa: E402
from data_consistency import assess_person  # noqa: E402
from lib import freeze, seed as seedmod  # noqa: E402

FROZEN_DIR = EVAL_DIR / "frozen" / "v4"
V3_FROZEN_DIR = EVAL_DIR / "frozen" / "v3"
CREATED_AT = "2026-11-05 00:00:00"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy_frozen(target: Path) -> None:
    for name in ("scenarios.json", "MANIFEST.json", "COVERAGE.md"):
        (target / name).write_bytes((FROZEN_DIR / name).read_bytes())


class V4ScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = v4.build()
        cls.text = v4.dump(cls.data)
        cls.frozen_text = (FROZEN_DIR / "scenarios.json").read_text(encoding="utf-8")
        cls.frozen_bytes = (FROZEN_DIR / "scenarios.json").read_bytes()
        cls.manifest = json.loads((FROZEN_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
        cls.scenarios = cls.data["scenarios"]
        cls.positives = [item for item in cls.scenarios if item["run"]]
        cls.negatives = [item for item in cls.scenarios if not item["run"]]
        cls.by_key = {item["key"]: item for item in cls.scenarios}
        cls.seed = seedmod.load_seed(REPO)

    # ------------------------------------------------------------ 形状/冻结
    def test_counts_and_shape(self):
        data = self.data
        self.assertEqual(data["protocol_version"], "v4-2026-11-05")
        self.assertEqual(data["seed"], 20261104)
        self.assertEqual(data["as_of"], "2026-11-04")
        self.assertEqual(data["scenario_count"], 48)
        self.assertEqual(data["positive_count"], 40)
        self.assertEqual(data["negative_count"], 8)
        self.assertEqual(data["deliver_count"], 8)
        self.assertEqual(len(self.scenarios), 48)
        self.assertEqual([item["key"] for item in self.scenarios],
                         [f"V4_{index:02d}" for index in range(1, 49)])
        for index, item in enumerate(self.scenarios, 1):
            self.assertEqual(item["slot"], index)
            self.assertEqual(item["account"], f"TEST_SCENARIO_V4_{index:02d}")
            self.assertEqual(item["deliver_count"], 8)
            for name in ("title", "profile", "preference", "moments", "expect",
                         "why", "ex_ante_capacity"):
                self.assertIn(name, item)
        self.assertEqual(self.data["grid"]["tier_counts"],
                         {"high": 16, "medium": 12, "low": 12})
        diversity = self.data["grid"]["diversity"]
        self.assertEqual(diversity["male"], 20)
        self.assertEqual(diversity["female"], 20)
        self.assertGreaterEqual(diversity["stores"], 16)
        self.assertEqual(diversity["lease_terms"], 5)

    def test_deterministic_and_frozen_bytes(self):
        self.assertEqual(v4.dump(v4.build()), self.text)
        self.assertEqual(self.text, self.frozen_text)
        self.assertEqual(_sha256(self.frozen_bytes),
                         self.manifest["scenarios"]["sha256"])
        self.assertEqual(v4.check(self.data), [])
        self.assertEqual(v4.verify(FROZEN_DIR), [])
        self.assertEqual(check_v4_freeze.check(FROZEN_DIR), [])

    # ------------------------------------------------------- slot / 昵称 / 文本
    def test_slot_and_nickname_are_fixed(self):
        nicknames = set()
        slots = set()
        for index, item in enumerate(self.positives, 1):
            profile = item["profile"]
            self.assertEqual(profile["nickname"], f"V4场景租客{index:02d}")
            self.assertEqual(item["slot"], index)
            nicknames.add(profile["nickname"])
            slots.add(item["slot"])
            self.assertIn(f"第 {index} 次", profile["self_intro"])
            self.assertIn(f"第 {index} 次", profile["roommate_expectation"])
        self.assertEqual(len(nicknames), 40)
        self.assertEqual(len(slots), 40)
        self.assertNotIn("第 208 次", self.frozen_text)
        self.assertNotIn("V3场景租客", self.frozen_text)
        self.assertNotIn("。。", self.frozen_text)
        for item in self.negatives:
            self.assertEqual(item["profile"]["nickname"],
                             f"V4场景租客{item['slot']:02d}")
            self.assertIn(f"第 {item['slot']} 次",
                          item["profile"]["roommate_expectation"])

    def test_text_cleaning_and_consistency(self):
        cleaned_keys = []
        for item in self.positives:
            profile = item["profile"]
            tags = profile["interest_tags"]
            self.assertGreaterEqual(len(tags), 3)
            self.assertFalse([tag for tag in tags if tag in v4.PET_TAGS],
                             (item["key"], tags))
            self.assertEqual(v4.text_pet_conflicts(profile), [], item["key"])
            consistency = assess_person(profile)
            self.assertGreater(consistency["score"], 0,
                               (item["key"], consistency["reasons"]))
            text = profile["self_intro"] + " " + profile["roommate_expectation"]
            found = [word for word in v4.PET_TEXT_WORDS if word in text]
            self.assertEqual(found, [], (item["key"], found))
            moments = " ".join(item["moments"])
            found = [word for word in v4.PET_TEXT_WORDS if word in moments]
            self.assertEqual(found, [], (item["key"], found))
            if profile["has_pet"] == "无" and v4.text_pet_conflicts(profile):
                self.fail(f"{item['key']} 文本宠物矛盾未修复")
        # 固定 4 个场景（seq%10==8）原本取到养宠类标签，必须被替换成中性标签
        for seq in (8, 18, 28, 38):
            item = self.by_key[f"V4_{seq:02d}"]
            self.assertEqual(item["profile"]["interest_tags"],
                             list(v4.FALLBACK_TAGS[:3]), item["key"])
            cleaned_keys.append(item["key"])
        self.assertEqual(self.data["grid"]["text_cleaning"]["scenarios"],
                         [{"key": key, "removed_count": 3} for key in cleaned_keys])
        self.assertEqual(self.data["grid"]["text_cleaning"]["removed_tags"], 12)

    # ------------------------------------------------------------- target/负向
    def test_targets_match_capacity_rule(self):
        for item in self.positives:
            expect = item["expect"]
            capacity = item["ex_ante_capacity"]
            unbounded = capacity["eligible_unbounded"]
            self.assertEqual(expect["target"], min(8, unbounded), item["key"])
            self.assertEqual(expect["target_rule"], "min(8, eligible_unbounded)")
            self.assertEqual(expect["requested"], 8)
            self.assertIs(expect["can_run"], True)
            self.assertIsNone(expect["blocker"])
            self.assertEqual(expect["ex_ante_eligible"], capacity["eligible"])
            self.assertEqual(expect["ex_ante_unbounded"], unbounded)
            self.assertGreaterEqual(capacity["eligible"], 1)
            self.assertGreaterEqual(unbounded, capacity["eligible"])
            if capacity["tier"] == "high":
                self.assertGreaterEqual(capacity["eligible"], 8)
            elif capacity["tier"] == "medium":
                self.assertTrue(4 <= capacity["eligible"] <= 7)
            else:
                self.assertEqual(capacity["tier"], "low")
                self.assertTrue(1 <= capacity["eligible"] <= 3)
        targets = [item["expect"]["target"] for item in self.positives]
        self.assertEqual(self.data["grid"]["target_distribution"]["8"],
                         targets.count(8))

    def test_negative_cross_tier_and_gender(self):
        self.assertEqual(len(self.negatives), 8)
        self.assertEqual([item["key"] for item in self.negatives],
                         [f"V4_{index:02d}" for index in range(41, 49)])
        moment_group = [item for item in self.negatives
                        if item["expect"]["blocker"] == "moment"]
        intro_group = [item for item in self.negatives
                       if item["expect"]["blocker"] == "intro"]
        self.assertEqual(len(moment_group), 4)
        self.assertEqual(len(intro_group), 4)
        source_indexes = []
        for item in self.negatives:
            self.assertIs(item["expect"]["can_run"], False)
            self.assertEqual(item["deliver_count"], 8)
            source_key = item["ex_ante_capacity"]["source_key"]
            source = self.by_key[source_key]
            self.assertIs(source["run"], True)
            source_indexes.append(self.positives.index(source))
        self.assertEqual(sorted(source_indexes),
                         list(v4.NEGATIVE_SOURCE_INDICES))
        for name, group in (("moment", moment_group), ("intro", intro_group)):
            genders = {item["profile"]["gender"] for item in group}
            tiers = {item["ex_ante_capacity"]["source_tier"] for item in group}
            self.assertEqual(len(genders), 2, name)
            self.assertGreaterEqual(len(tiers), 2, name)
        for item in moment_group:
            self.assertEqual(item["moments"], [])
            self.assertTrue(item["profile"]["self_intro"])
        for item in intro_group:
            self.assertEqual(item["profile"]["self_intro"], "")
            self.assertTrue(item["moments"])
            self.assertIn("必填", item["expect"]["note"])

    # ---------------------------------------------------------------- MANIFEST
    def test_manifest_fingerprints_reproducible(self):
        manifest = self.manifest
        self.assertEqual(manifest["version"], "v4")
        self.assertEqual(manifest["protocol_version"], "v4-2026-11-05")
        self.assertEqual(manifest["seed"], 20261104)
        self.assertEqual(manifest["as_of"], "2026-11-04")
        self.assertEqual(manifest["scenario_count"], 48)
        self.assertEqual(manifest["positive_count"], 40)
        self.assertEqual(manifest["negative_count"], 8)
        self.assertEqual(manifest["deliver_count"], 8)
        self.assertEqual(manifest["scenarios"]["file"],
                         "eval/frozen/v4/scenarios.json")
        self.assertEqual(manifest["scenarios"]["sha256"],
                         _sha256(self.frozen_bytes))
        self.assertEqual(manifest["labels"]["status"], "pending")
        self.assertTrue(manifest["labels"]["method"])
        self.assertEqual(manifest["supply_additions"], 0)
        self.assertTrue(manifest["created_at"])
        pool = manifest["pool"]
        self.assertEqual(pool["members"], 900)
        self.assertEqual(pool["approved"], 841)
        self.assertEqual(pool["base_sql_sha256"], freeze.base_sql_sha256(REPO))
        self.assertEqual(pool["pool_digest"], freeze.pool_digest(self.seed))
        self.assertTrue(str(pool["source"]).endswith("01-paringbot.sql"))
        rebuilt = v4.build_manifest(self.frozen_bytes, self.data, REPO,
                                    created_at=manifest["created_at"],
                                    base=FROZEN_DIR)
        self.assertEqual(rebuilt, manifest)

    # ------------------------------------------------------- 篡改 fail-closed
    def test_verify_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _copy_frozen(base)
            manifest = v4.build_manifest((base / "scenarios.json").read_bytes(),
                                         self.data, REPO, created_at=CREATED_AT,
                                         base=base)
            (base / "MANIFEST.json").write_text(v4.dump_manifest(manifest),
                                               encoding="utf-8")
            self.assertEqual(v4.verify(base, REPO), [])
            self.assertEqual(check_v4_freeze.check(base, REPO), [])

            payload = json.loads((base / "scenarios.json").read_text(encoding="utf-8"))
            payload["scenarios"][0]["title"] += "（改）"
            (base / "scenarios.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(v4.verify(base, REPO))
            self.assertTrue(check_v4_freeze.check(base, REPO))

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _copy_frozen(base)
            broken = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
            broken["protocol_version"] = "v4-2026-11-04"
            broken["scenarios"]["sha256"] = "0" * 64
            (base / "MANIFEST.json").write_text(
                json.dumps(broken, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(v4.verify(base, REPO))
            self.assertTrue(check_v4_freeze.check(base, REPO))

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _copy_frozen(base)
            (base / "COVERAGE.md").write_text("# 手改过的覆盖报告\n", encoding="utf-8")
            self.assertTrue(v4.verify(base, REPO))

    # ------------------------------------------------------- 标签工具（CSV/judge）
    def _csv_rows(self) -> list[dict]:
        rows = []
        for index, item in enumerate(self.positives):
            for offset in range(2):
                rows.append({
                    "pair_id": f"{item['key']}-pair{offset}",
                    "applicant_id": item["account"],
                    "candidate_id": str(1000 + index * 2 + offset),
                    "score": str((index + offset) % 4),
                    "annotator": "tester",
                    "delivered": "true" if offset == 0 else "false",
                })
        return rows

    def test_labels_tool_csv_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _copy_frozen(base)
            manifest = v4.build_manifest((base / "scenarios.json").read_bytes(),
                                         self.data, REPO, created_at=CREATED_AT,
                                         base=base)
            (base / "MANIFEST.json").write_text(v4.dump_manifest(manifest),
                                               encoding="utf-8")
            csv_path = base / "labels-input.csv"
            rows = self._csv_rows()
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            raw = v4labels.read_csv_rows(csv_path)
            document = v4labels.build_labels_document(
                raw, v4labels.METHOD_CSV,
                {"kind": "csv", "file": str(csv_path), "sha256": _sha256(csv_path.read_bytes())},
                self.data)
            self.assertEqual(document["coverage"]["covered"], 40)
            self.assertEqual(document["coverage"]["label_count"], 80)
            self.assertEqual(v4labels.check_labels_document(document, self.data), [])
            self.assertEqual(v4labels.main(["--from-csv", str(csv_path), "--write",
                                            "--frozen-dir", str(base), "--quiet"]), 0)
            self.assertEqual(v4labels.check(base), [])
            frozen_manifest = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen_manifest["labels"]["status"], "ready")
            self.assertEqual(frozen_manifest["labels"]["count"], 80)
            self.assertEqual(frozen_manifest["labels"]["sha256"],
                             _sha256((base / "labels.json").read_bytes()))
            # 带冻结标签的目录整体守卫（labels=ready + schema/覆盖）也要通过
            self.assertEqual(check_v4_freeze.check(base, REPO), [])
            self.assertEqual(v4.verify(base, REPO), [])
            # 篡改标签：删一条 → 覆盖/计数错误
            labels = json.loads((base / "labels.json").read_text(encoding="utf-8"))
            labels["labels"] = labels["labels"][:-1]
            (base / "labels.json").write_text(
                json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(v4labels.check(base))
            self.assertTrue(check_v4_freeze.check(base, REPO))

    def test_labels_tool_judge_and_invalid_rows(self):
        rows = [{
            "pair_id": f"{item['key']}-judge",
            "applicant": item["key"],
            "candidate": 2000 + index,
            "score": index % 4,
        } for index, item in enumerate(self.positives)]
        with tempfile.TemporaryDirectory() as tmp:
            judge_path = Path(tmp) / "judge.json"
            judge_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            parsed = v4labels.read_judge_rows(judge_path)
            document = v4labels.build_labels_document(
                parsed, v4labels.METHOD_JUDGE,
                {"kind": "json-judge", "file": str(judge_path),
                 "sha256": _sha256(judge_path.read_bytes())}, self.data)
            self.assertEqual(document["method"], v4labels.METHOD_JUDGE)
            self.assertEqual(document["labels"][0]["annotator"], v4labels.METHOD_JUDGE)
            self.assertEqual(v4labels.check_labels_document(document, self.data), [])
        # 非法输入：score 越界 / 未覆盖 40 个正向 / 重复 pair_id
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bad_csv = base / "bad.csv"
            bad_rows = self._csv_rows()
            bad_rows[0]["score"] = "4"
            with bad_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(bad_rows[0]))
                writer.writeheader()
                writer.writerows(bad_rows)
            with self.assertRaises(v4labels.LabelInputError):
                v4labels.build_labels_document(
                    v4labels.read_csv_rows(bad_csv), v4labels.METHOD_CSV,
                    {"kind": "csv", "file": "bad.csv", "sha256": "0"}, self.data)
            partial = self._csv_rows()[:2]
            partial_doc = v4labels.build_labels_document(
                partial, v4labels.METHOD_CSV,
                {"kind": "csv", "file": "partial.csv", "sha256": "0"}, self.data)
            self.assertTrue(v4labels.check_labels_document(partial_doc, self.data))
            duplicate = [self._csv_rows()[0], self._csv_rows()[0]]
            with self.assertRaises(v4labels.LabelInputError):
                v4labels.build_labels_document(
                    duplicate, v4labels.METHOD_CSV,
                    {"kind": "csv", "file": "dup.csv", "sha256": "0"}, self.data)


class V3FrozenCompatibilityTest(unittest.TestCase):
    """v3 生成器只新增 opt-in 参数：默认输出必须与冻结文件逐字节一致。"""

    def test_v3_scenarios_bytes_unchanged(self):
        rebuilt = v3.dump_scenarios(v3.build_scenarios(REPO))
        frozen = (V3_FROZEN_DIR / "scenarios.json").read_text(encoding="utf-8")
        self.assertEqual(rebuilt, frozen)
        self.assertEqual(
            hashlib.sha256(rebuilt.encode("utf-8")).hexdigest(),
            "9dd20c0e4388aa236f88bc546a8b4023da403fe18f37a52002f4a21b32b0968d")

    def test_v3_opt_in_parameters_do_not_leak(self):
        """新增参数只在显式传入时生效，不影响默认档案/文本。"""
        seed_data = seedmod.load_seed(REPO)
        pool = seedmod.approved_candidates(seed_data)
        spec = {"slot": 1, "extra": None, "scope": "同片区", "tier": "high", "_pool": pool}
        default = v3._make_applicant(spec, 1, "男", "6-12个月")
        explicit = v3._make_applicant(
            spec, 1, "男", "6-12个月",
            tags_override=list(default[1]["interest_tags"]),
            nickname=default[1]["nickname"])
        self.assertEqual(default[1], explicit[1])
        self.assertEqual(default[2], explicit[2])


if __name__ == "__main__":
    unittest.main()
