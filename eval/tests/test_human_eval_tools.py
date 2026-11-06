#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工盲评工具链离线测试：materials → 校准集 → 双人一致 → 人工验收。

覆盖：
- build_calibration：分层抽样、A/B 重随机化（seed 固定）、key 映射、模板产物、
  系统元数据泄漏/重复 pair_id/缺 key 的 fail-closed 校验、样本不足退出码、拒绝覆盖标注；
- agreement：一致率/Cohen kappa/by_stratum、分歧回填裁决表、裁决结果保留、未填/非法值、
  kappa 门禁退出码；
- acceptance：15% 分层抽样（交付/对照档位覆盖）、与 judge 方向一致率/kappa 签核、
  未填/方向不符/缺列、key 兜底抽样。
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

from human_eval import acceptance, agreement, build_calibration  # noqa: E402
from lib.stats import cohen_kappa  # noqa: E402
from quality_spec import JUDGE_GATES, SAMPLE_FLOORS  # noqa: E402


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------


def person(name: str, occupation: str = "普通", **overrides) -> dict:
    data = {
        "gender": "女", "age": 27, "rent_budget": 4000, "lease_term": "3-6个月",
        "store": "徐汇", "store_id": 1, "schedule_type": "正常作息", "tidiness": "整洁",
        "has_pet": "无", "smoking": "不吸烟", "occupation": occupation,
        "self_intro": f"{name} 的自我介绍", "roommate_expectation": "作息规律",
        "interest_tags": ["养猫"], "preference": {"detail": {"pet_accept": "接受"}},
    }
    data.update(overrides)
    return data


def make_materials(near_miss: int = 12, rejected: int = 4, random_pool: int = 4) -> dict:
    """合成 quality_pairwise --emit-materials 的合法输出（含 delivered/control 材料）。"""
    materials = {"protocol": "quality-v1-2026-11-06", "pairs": [], "key": {}}
    index = 0
    for stratum, count in (("near_miss", near_miss), ("rejected", rejected),
                           ("random", random_pool)):
        for offset in range(count):
            pair_id = f"{stratum}-{offset:03d}"
            delivered = person(f"交付{index}", occupation="交付本人")
            control = person(f"对照{index}", occupation="对照")
            side = "A" if index % 2 == 0 else "B"
            candidate_a, candidate_b = ((delivered, control) if side == "A"
                                        else (control, delivered))
            materials["pairs"].append({
                "pair_id": pair_id,
                "stratum": stratum,
                "applicant": person(f"申请{index}", occupation="申请方"),
                "candidate_a": candidate_a,
                "candidate_b": candidate_b,
            })
            materials["key"][pair_id] = {
                "delivered_side": side,
                "delivered_id": 1000 + index,
                "control_id": 2000 + index,
                "stratum": stratum,
            }
            index += 1
    return materials


def read_csv_rows(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv_rows(path: Path, columns, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tempdir.name)
        self.addCleanup(self._tempdir.cleanup)

    def write_json(self, name: str, payload) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def read_json(self, path: Path):
        return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# build_calibration
# ---------------------------------------------------------------------------


class BuildCalibrationTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.materials = make_materials()
        self.materials_path = self.write_json("materials.json", self.materials)

    def build(self, strata: str = "near_miss=8,rejected=2,random=2",
              seed: str = "20261106", out_name: str = "calibration") -> tuple[int, Path]:
        out_dir = self.tmp / out_name
        code = build_calibration.main(["--materials", str(self.materials_path),
                                       "--out-dir", str(out_dir),
                                       "--strata", strata, "--seed", seed])
        return code, out_dir

    def test_outputs_strata_and_key_mapping(self):
        code, out_dir = self.build()
        self.assertEqual(code, 0)
        blind = self.read_json(out_dir / "blind_set.json")
        key = self.read_json(out_dir / "key.json")
        self.assertEqual(len(blind["pairs"]), 12)
        self.assertEqual(Counter(pair["stratum"] for pair in blind["pairs"]),
                         {"near_miss": 8, "rejected": 2, "random": 2})
        self.assertEqual(blind["quotas"], {"near_miss": 8, "rejected": 2, "random": 2})
        self.assertEqual(set(key), {pair["pair_id"] for pair in blind["pairs"]})
        sides = Counter()
        for pair in blind["pairs"]:
            entry = key[pair["pair_id"]]
            self.assertEqual(entry["stratum"], pair["stratum"])
            self.assertIn(entry["delivered_side"], ("A", "B"))
            self.assertNotEqual(entry["delivered_id"], entry["control_id"])
            delivered = pair["candidate_a"] if entry["delivered_side"] == "A" else pair["candidate_b"]
            control = pair["candidate_b"] if entry["delivered_side"] == "A" else pair["candidate_a"]
            self.assertEqual(delivered["occupation"], "交付本人")
            self.assertEqual(control["occupation"], "对照")
            sides[entry["delivered_side"]] += 1
        self.assertGreaterEqual(min(sides["A"], sides["B"]), 1)  # A/B 顺序确实随机化
        dumped = json.dumps(blind, ensure_ascii=False)
        for needle in ("delivered_side", "delivered_id", "control_id", "audit_status",
                       "screen_score", "evidence", "role"):
            self.assertNotIn(needle, dumped)

    def test_annotation_templates_and_empty_adjudication(self):
        code, out_dir = self.build()
        self.assertEqual(code, 0)
        for filename in ("annotations_annotator_a.csv", "annotations_annotator_b.csv"):
            rows = read_csv_rows(out_dir / filename)
            self.assertEqual(len(rows), 12)
            self.assertEqual(set(rows[0]), set(build_calibration.ANNOTATION_COLUMNS))
            self.assertTrue(all(not row["winner"] and not row["notes"] for row in rows))
        self.assertEqual((out_dir / "adjudication.csv").read_text(encoding="utf-8").splitlines(),
                         [",".join(build_calibration.ADJUDICATION_COLUMNS)])
        self.assertEqual(read_csv_rows(out_dir / "adjudication.csv"), [])

    def test_same_seed_is_deterministic(self):
        _, first = self.build(out_name="first")
        _, second = self.build(out_name="second")
        self.assertEqual((first / "blind_set.json").read_text(encoding="utf-8"),
                         (second / "blind_set.json").read_text(encoding="utf-8"))
        self.assertEqual((first / "key.json").read_text(encoding="utf-8"),
                         (second / "key.json").read_text(encoding="utf-8"))

    def test_different_seed_changes_ab_order(self):
        # 档位配额取满，保证两次抽到同一批 pair，差异只来自 A/B 随机化
        full = "near_miss=12,rejected=4,random=4"
        _, first = self.build(strata=full, seed="20261106", out_name="seed1")
        _, second = self.build(strata=full, seed="7", out_name="seed2")
        first_sides = {pid: entry["delivered_side"]
                       for pid, entry in self.read_json(first / "key.json").items()}
        second_sides = {pid: entry["delivered_side"]
                        for pid, entry in self.read_json(second / "key.json").items()}
        self.assertEqual(set(first_sides), set(second_sides))
        self.assertNotEqual(first_sides, second_sides)

    def test_forbidden_material_rejected(self):
        for field, value in (("screen_score", 95), ("delivered", True),
                             ("audit_status", "通过"), ("A_role", "delivered"),
                             ("delivered_rank", 1), ("evidence", ["硬规则"])):
            materials = make_materials()
            materials["pairs"][0]["candidate_a"][field] = value
            with self.assertRaises(ValueError, msg=field):
                build_calibration.build(materials, strata_counts={"near_miss": 1})

    def test_invalid_contract_rejected(self):
        duplicated = make_materials()
        duplicated["pairs"].append(dict(duplicated["pairs"][0]))
        with self.assertRaises(ValueError):
            build_calibration.build(duplicated, strata_counts={"near_miss": 2})

        missing_key = make_materials()
        missing_key["key"].pop(missing_key["pairs"][0]["pair_id"])
        with self.assertRaises(ValueError):
            build_calibration.build(missing_key, strata_counts={"near_miss": 2})

        bad_side = make_materials()
        bad_side["key"][bad_side["pairs"][0]["pair_id"]]["delivered_side"] = "C"
        with self.assertRaises(ValueError):
            build_calibration.build(bad_side, strata_counts={"near_miss": 2})

        no_pairs = {"protocol": "x", "pairs": [], "key": {}}
        with self.assertRaises(ValueError):
            build_calibration.build(no_pairs)

    def test_shortfall_is_fail_closed_but_writes_outputs(self):
        out_dir = self.tmp / "short"
        code = build_calibration.main(["--materials", str(self.materials_path),
                                       "--out-dir", str(out_dir), "--n", "100"])
        self.assertEqual(code, 1)
        blind = self.read_json(out_dir / "blind_set.json")
        self.assertEqual(blind["n"], 20)  # 12+4+4 全部可用，但配额 60/20/20 不足
        self.assertIn("near_miss", blind["shortfalls"])
        allow = build_calibration.main(["--materials", str(self.materials_path),
                                        "--out-dir", str(out_dir), "--n", "100",
                                        "--allow-shortfall", "--force"])
        self.assertEqual(allow, 0)

    def test_refuses_to_overwrite_existing_annotations(self):
        code, out_dir = self.build()
        self.assertEqual(code, 0)
        path = out_dir / "annotations_annotator_a.csv"
        rows = read_csv_rows(path)
        rows[0]["winner"] = "A"
        write_csv_rows(path, build_calibration.ANNOTATION_COLUMNS, rows)
        code = build_calibration.main(["--materials", str(self.materials_path),
                                       "--out-dir", str(out_dir),
                                       "--strata", "near_miss=8,rejected=2,random=2"])
        self.assertEqual(code, 3)
        self.assertEqual(read_csv_rows(path)[0]["winner"], "A")  # 人工数据未被覆盖


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------


class AgreementTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.materials = make_materials()
        self.materials_path = self.write_json("materials.json", self.materials)
        self.out_dir = self.tmp / "calibration"
        code = build_calibration.main([
            "--materials", str(self.materials_path), "--out-dir", str(self.out_dir),
            "--strata", "near_miss=6,rejected=2,random=2", "--seed", "20261106"])
        self.assertEqual(code, 0)
        blind = self.read_json(self.out_dir / "blind_set.json")
        self.pair_ids = [pair["pair_id"] for pair in blind["pairs"]]
        self.key = self.read_json(self.out_dir / "key.json")

    def annotate(self, winner_a: dict, winner_b: dict) -> None:
        for name, mapping in (("a", winner_a), ("b", winner_b)):
            path = self.out_dir / f"annotations_annotator_{name}.csv"
            rows = read_csv_rows(path)
            for row in rows:
                row["winner"] = mapping.get(row["pair_id"], "")
                row["confidence"] = "high" if row["winner"] else ""
            write_csv_rows(path, agreement.ANNOTATION_COLUMNS, rows)

    def alternating(self, flip: set[str] = frozenset()) -> dict:
        mapping = {}
        for index, pair_id in enumerate(self.pair_ids):
            winner = "A" if index % 2 == 0 else "B"
            if pair_id in flip:
                winner = "B" if winner == "A" else "A"
            mapping[pair_id] = winner
        return mapping

    def run_agreement(self) -> tuple[int, dict]:
        code = agreement.main(["--dir", str(self.out_dir)])
        return code, self.read_json(self.out_dir / "agreement.json")

    def test_perfect_agreement_is_usable(self):
        mapping = self.alternating()
        self.annotate(mapping, mapping)
        code, result = self.run_agreement()
        self.assertEqual(code, 0)
        self.assertTrue(result["usable"])
        self.assertEqual(result["n"], 10)
        self.assertEqual(result["agreement"], 1.0)
        self.assertAlmostEqual(result["kappa"], 1.0, places=6)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(sum(item["n"] for item in result["by_stratum"].values()), 10)
        self.assertEqual(result["threshold"]["value"], JUDGE_GATES["human_kappa_min"])
        # 双人一致的行自动裁决，adjudication.csv 可直接作为人工真值标签
        adjudication = read_csv_rows(self.out_dir / "adjudication.csv")
        self.assertEqual(len(adjudication), 10)
        self.assertEqual(result["adjudicated"],
                         {"total": 10, "auto_agreed": 10, "pending": 0})
        for row in adjudication:
            self.assertEqual(row["final_winner"], mapping[row["pair_id"]])

    def test_disagreements_filled_into_adjudication(self):
        mapping_a = self.alternating()
        flipped = set(self.pair_ids[:2])
        mapping_b = self.alternating(flip=flipped)
        self.annotate(mapping_a, mapping_b)
        code, result = self.run_agreement()
        labels_a = [mapping_a[pair_id] for pair_id in self.pair_ids]
        labels_b = [mapping_b[pair_id] for pair_id in self.pair_ids]
        expected_agreement = sum(1 for x, y in zip(labels_a, labels_b) if x == y) / len(labels_a)
        expected_kappa = cohen_kappa(labels_a, labels_b)
        self.assertEqual(result["n"], 10)
        self.assertAlmostEqual(result["agreement"], round(expected_agreement, 4), places=4)
        self.assertAlmostEqual(result["kappa"], round(expected_kappa, 4), places=4)
        self.assertEqual(result["usable"], expected_kappa >= JUDGE_GATES["human_kappa_min"])
        self.assertEqual(code, 0 if result["usable"] else 1)
        self.assertEqual(sorted(row["pair_id"] for row in result["disagreements"]),
                         sorted(flipped))
        adjudication = read_csv_rows(self.out_dir / "adjudication.csv")
        self.assertEqual(len(adjudication), 10)
        self.assertEqual(result["adjudicated"],
                         {"total": 10, "auto_agreed": 8, "pending": 2})
        by_id = {row["pair_id"]: row for row in adjudication}
        for pair_id in flipped:
            self.assertFalse(by_id[pair_id]["final_winner"])
            self.assertIn("分歧", by_id[pair_id]["notes"])
        for pair_id in set(self.pair_ids) - flipped:
            self.assertEqual(by_id[pair_id]["final_winner"], mapping_a[pair_id])

        # 人工已裁决的结果不能被重跑覆盖
        dispute_id = sorted(flipped)[0]
        for row in adjudication:
            if row["pair_id"] == dispute_id:
                row["final_winner"] = "A"
                row["notes"] = "已裁决"
        write_csv_rows(self.out_dir / "adjudication.csv",
                       agreement.ADJUDICATION_COLUMNS, adjudication)
        self.run_agreement()
        preserved = {row["pair_id"]: row for row in
                     read_csv_rows(self.out_dir / "adjudication.csv")}
        self.assertEqual(preserved[dispute_id]["final_winner"], "A")
        self.assertEqual(preserved[dispute_id]["notes"], "已裁决")
        agreed_id = next(pair_id for pair_id in self.pair_ids if pair_id not in flipped)
        self.assertEqual(preserved[agreed_id]["final_winner"], mapping_a[agreed_id])

    def test_low_kappa_exits_nonzero(self):
        mapping_a = {pair_id: ("A" if index < 5 else "B")
                     for index, pair_id in enumerate(self.pair_ids)}
        mapping_b = {pair_id: ("B" if mapping_a[pair_id] == "A" else "A")
                     for pair_id in self.pair_ids}
        self.annotate(mapping_a, mapping_b)
        code, result = self.run_agreement()
        self.assertEqual(code, 1)
        self.assertFalse(result["usable"])
        self.assertEqual(result["agreement"], 0.0)
        self.assertLess(result["kappa"], JUDGE_GATES["human_kappa_min"])
        self.assertTrue(any("kappa" in reason for reason in result["reasons"]))

    def test_unfilled_and_invalid_are_not_usable(self):
        mapping_a = self.alternating()
        mapping_b = dict(mapping_a)
        mapping_b[self.pair_ids[0]] = ""  # 未填
        self.annotate(mapping_a, mapping_b)
        code, result = self.run_agreement()
        self.assertEqual(code, 1)
        self.assertFalse(result["usable"])
        self.assertIn(self.pair_ids[0], result["unfilled"])
        self.assertTrue(any("未完成" in reason for reason in result["reasons"]))
        adjudicated = {row["pair_id"] for row in
                       read_csv_rows(self.out_dir / "adjudication.csv")}
        self.assertNotIn(self.pair_ids[0], adjudicated)  # 未填的 pair 不写裁决表

        mapping_b[self.pair_ids[0]] = "X"  # 非法值
        self.annotate(mapping_a, mapping_b)
        code, result = self.run_agreement()
        self.assertEqual(code, 1)
        self.assertFalse(result["usable"])
        self.assertEqual(result["invalid"][0]["winner"], "X")

    def test_missing_annotations_file(self):
        (self.out_dir / "annotations_annotator_b.csv").unlink()
        code = agreement.main(["--dir", str(self.out_dir)])
        self.assertEqual(code, 1)
        self.assertFalse((self.out_dir / "agreement.json").exists())


# ---------------------------------------------------------------------------
# acceptance
# ---------------------------------------------------------------------------


class AcceptanceTest(TempDirCase):
    def setUp(self):
        super().setUp()
        self.materials = make_materials()
        self.materials_path = self.write_json("materials.json", self.materials)
        self.calibration = self.tmp / "calibration"
        code = build_calibration.main([
            "--materials", str(self.materials_path), "--out-dir", str(self.calibration),
            "--strata", "near_miss=12,rejected=4,random=4", "--seed", "20261106"])
        self.assertEqual(code, 0)
        self.key = self.read_json(self.calibration / "key.json")
        self.pair_ids = sorted(self.key)
        # 交错 judge 方向，保证交付/对照两个方向都出现
        self.pairs = [{"pair_id": pair_id,
                       "stratum": self.key[pair_id]["stratum"],
                       "winner": "delivered" if index % 2 == 0 else "control"}
                      for index, pair_id in enumerate(self.pair_ids)]
        self.report_path = self.write_json("quality-report.json", {
            "metric": "match_quality", "protocol": "quality-v1-2026-11-06",
            "n_pairs": len(self.pairs), "pairs": self.pairs})
        self.key_path = self.calibration / "key.json"

    def run_sampling(self, out_name: str = "acceptance.csv", rate: str = "0.15") -> tuple[int, Path]:
        out = self.tmp / out_name
        code = acceptance.main(["--report", str(self.report_path), "--key", str(self.key_path),
                                "--out", str(out), "--rate", rate, "--seed", "20261106"])
        return code, out

    def judge_direction(self, pair_id: str) -> str:
        return next(row["winner"] for row in self.pairs if row["pair_id"] == pair_id)

    def side_for(self, pair_id: str, direction: str) -> str:
        delivered_side = self.key[pair_id]["delivered_side"]
        if direction == "delivered":
            return delivered_side
        return "B" if delivered_side == "A" else "A"

    def test_sample_rate_strata_and_determinism(self):
        code, out = self.run_sampling()
        self.assertEqual(code, 0)
        rows = read_csv_rows(out)
        self.assertEqual(len(rows), 4)  # ceil(12*.15)=2 + 1 + 1
        self.assertEqual(Counter(row["stratum"] for row in rows),
                         {"near_miss": 2, "rejected": 1, "random": 1})
        self.assertTrue(all(not row["human_winner"] and not row["notes"] for row in rows))
        self.assertEqual(set(rows[0]), set(acceptance.ACCEPTANCE_COLUMNS))
        code, other = self.run_sampling(out_name="acceptance_2.csv")
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(encoding="utf-8"), other.read_text(encoding="utf-8"))
        self.assertEqual(acceptance.SAMPLE_FLOORS["human_acceptance_rate"],
                         SAMPLE_FLOORS["human_acceptance_rate"])

    def test_default_rate_comes_from_quality_spec(self):
        self.assertEqual(SAMPLE_FLOORS["human_acceptance_rate"], 0.15)
        described = acceptance.main(["--report", str(self.report_path),
                                     "--key", str(self.key_path),
                                     "--out", str(self.tmp / "default.csv"),
                                     "--seed", "20261106"])
        self.assertEqual(described, 0)
        explicit = acceptance.main(["--report", str(self.report_path),
                                    "--key", str(self.key_path),
                                    "--out", str(self.tmp / "explicit.csv"),
                                    "--rate", "0.15", "--seed", "20261106"])
        self.assertEqual(explicit, 0)
        self.assertEqual((self.tmp / "default.csv").read_text(encoding="utf-8"),
                         (self.tmp / "explicit.csv").read_text(encoding="utf-8"))

    def fill_acceptance(self, path: Path, mutate=None) -> list[dict]:
        rows = read_csv_rows(path)
        for row in rows:
            pair_id = row["pair_id"]
            direction = self.judge_direction(pair_id)
            row["human_winner"] = self.side_for(pair_id, direction)
        if mutate:
            rows = mutate(rows)
        write_csv_rows(path, acceptance.ACCEPTANCE_COLUMNS, rows)
        return rows

    def run_check(self, csv_path: Path, json_name: str = "signoff.json",
                  report_path: Path | None = None) -> tuple[int, dict]:
        json_path = self.tmp / json_name
        code = acceptance.main(["--report", str(report_path or self.report_path),
                                "--key", str(self.key_path),
                                "--check", str(csv_path), "--json", str(json_path)])
        return code, self.read_json(json_path)

    def test_check_passes_when_human_matches_judge(self):
        code, out = self.run_sampling()
        self.assertEqual(code, 0)
        rows = read_csv_rows(out)
        sampled = sorted(row["pair_id"] for row in rows)
        # 用一份方向交替的核对报告，保证 delivered/control 两类都出现（kappa 可计算）
        directions = {pair_id: ("delivered" if index % 2 == 0 else "control")
                      for index, pair_id in enumerate(sampled)}
        check_report = self.write_json("check-report.json", {
            "metric": "match_quality",
            "pairs": [{"pair_id": pair_id, "stratum": self.key[pair_id]["stratum"],
                       "winner": directions[pair_id]} for pair_id in sampled]})
        for row in rows:
            row["human_winner"] = self.side_for(row["pair_id"], directions[row["pair_id"]])
        write_csv_rows(out, acceptance.ACCEPTANCE_COLUMNS, rows)
        code, signoff = self.run_check(out, report_path=check_report)
        self.assertEqual(code, 0)
        self.assertTrue(signoff["usable"])
        self.assertEqual(signoff["n"], 4)
        self.assertEqual(signoff["rows"], 4)
        self.assertEqual(signoff["agreement"], 1.0)
        self.assertAlmostEqual(signoff["kappa"], 1.0, places=6)
        self.assertEqual(signoff["reasons"], [])
        self.assertEqual(signoff["mismatches"], [])
        self.assertEqual(signoff["threshold"]["value"], JUDGE_GATES["human_kappa_min"])

    def test_check_accepts_direction_vocabulary(self):
        out = self.tmp / "mixed.csv"
        rows = []
        for index, pair_id in enumerate(self.pair_ids[:4]):
            direction = self.judge_direction(pair_id)
            # 前两行用 delivered/control 词表，后两行用 A/B 词表（都需要 key 折算）
            winner = (direction if index < 2 else self.side_for(pair_id, direction))
            rows.append({"pair_id": pair_id, "stratum": self.key[pair_id]["stratum"],
                         "human_winner": winner, "notes": ""})
        write_csv_rows(out, acceptance.ACCEPTANCE_COLUMNS, rows)
        code, signoff = self.run_check(out)
        self.assertEqual(code, 0)
        self.assertTrue(signoff["usable"])
        self.assertEqual(signoff["agreement"], 1.0)

    def test_check_rejects_mismatch(self):
        out = self.tmp / "wrong.csv"
        rows = []
        for pair_id in self.pair_ids[:4]:
            direction = self.judge_direction(pair_id)
            opposite = "control" if direction == "delivered" else "delivered"
            rows.append({"pair_id": pair_id, "stratum": self.key[pair_id]["stratum"],
                         "human_winner": opposite, "notes": ""})
        write_csv_rows(out, acceptance.ACCEPTANCE_COLUMNS, rows)
        code, signoff = self.run_check(out)
        self.assertEqual(code, 1)
        self.assertFalse(signoff["usable"])
        self.assertEqual(signoff["agreement"], 0.0)
        self.assertEqual(len(signoff["mismatches"]), 4)
        self.assertTrue(any("kappa" in reason for reason in signoff["reasons"]))

    def test_check_rejects_missing_values(self):
        code, out = self.run_sampling()
        self.assertEqual(code, 0)
        rows = self.fill_acceptance(out)
        rows[0]["human_winner"] = ""
        write_csv_rows(out, acceptance.ACCEPTANCE_COLUMNS, rows)
        code, signoff = self.run_check(out)
        self.assertEqual(code, 1)
        self.assertFalse(signoff["usable"])
        self.assertEqual(signoff["missing"], [rows[0]["pair_id"]])
        self.assertTrue(any("未填" in reason for reason in signoff["reasons"]))

    def test_sampling_falls_back_to_key(self):
        report_path = self.write_json("report-without-pairs.json",
                                      {"metric": "match_quality", "n_pairs": 20})
        out = self.tmp / "fallback.csv"
        code = acceptance.main(["--report", str(report_path), "--key", str(self.key_path),
                                "--out", str(out), "--rate", "0.15", "--seed", "20261106"])
        self.assertEqual(code, 0)
        rows = read_csv_rows(out)
        self.assertEqual(len(rows), 4)
        self.assertEqual(Counter(row["stratum"] for row in rows),
                         {"near_miss": 2, "rejected": 1, "random": 1})
        self.assertTrue(all(row["pair_id"] in self.key for row in rows))

    def test_sampling_from_nested_quality_report(self):
        # quality_report.py 把指标 payload 收在 metrics.<metric>.pairs 下，抽样要能下钻
        nested = self.write_json("nested-report.json", {
            "protocol": "quality-v1-2026-11-06",
            "metrics": {"match_quality": {"metric": "match_quality", "pairs": self.pairs}}})
        out = self.tmp / "nested-acceptance.csv"
        code = acceptance.main(["--report", str(nested), "--key", str(self.key_path),
                                "--out", str(out), "--rate", "0.15", "--seed", "20261106"])
        self.assertEqual(code, 0)
        rows = read_csv_rows(out)
        self.assertEqual(len(rows), 4)
        self.assertEqual(Counter(row["stratum"] for row in rows),
                         {"near_miss": 2, "rejected": 1, "random": 1})

    def test_judge_direction_compat_quality_pairwise(self):
        self.assertEqual(acceptance.judge_direction({"winner": "delivered"}), "delivered")
        self.assertEqual(acceptance.judge_direction({"delivered_win": True}), "delivered")
        self.assertEqual(acceptance.judge_direction({"control_win": True}), "control")
        self.assertEqual(acceptance.judge_direction({"tie": True}), "tie")
        # 双向交换：forward A=delivered、backward A=control，两条都指 delivered 才算
        self.assertEqual(acceptance.judge_direction({"verdicts": ["A", "B"]}), "delivered")
        self.assertEqual(acceptance.judge_direction({"verdicts": ["B", "A"]}), "control")
        self.assertEqual(acceptance.judge_direction({"verdicts": ["tie", "tie"]}), "tie")
        self.assertIsNone(acceptance.judge_direction({"verdicts": ["A", "A"]}))
        self.assertEqual(acceptance.judge_direction({
            "verdicts": [{"winner": "A", "delivered_side": "A"},
                         {"winner": "B", "delivered_side": "B"}]}), "delivered")
        self.assertIsNone(acceptance.judge_direction({}))


if __name__ == "__main__":
    unittest.main()
