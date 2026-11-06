"""2026-11 审计修复的回归测试：基线 provenance、门禁探针、统计口径、冻结守卫。

全部离线（不需要 DB/模型），与 report.py / check_freeze.py / lib/metrics.py 的真实实现联动。
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import check_freeze
import report
from lib import freeze as freeze_lib
from lib import metrics

REPO = EVAL.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _labels_hash() -> str:
    return _sha(REPO / "eval" / "frozen" / "v3" / "labels.json")


def _scenarios_hash() -> str:
    return _sha(REPO / "eval" / "frozen" / "v3" / "scenarios.json")


def _base_manifest() -> dict:
    return json.loads((REPO / "eval" / "frozen" / "v3" / "MANIFEST.json").read_text(encoding="utf-8"))


def _baseline_payload(**overrides) -> dict:
    payload = {
        "schema_version": 2,
        "protocol_version": "v3-2026-11-04",
        "labels_sha256": _labels_hash(),
        "scenarios_sha256": _scenarios_hash(),
        "source": {"code_commit": "test-commit", "run_id": "test"},
        "model_configs": [{"purpose": "审核", "model_name": "deepseek-flash"}],
        "db_profile": "eval",
        "failures": 0,
        "delivered_total": 41,
        "per_scenario": {
            "V3_01": {"delivered": [8], "target": 8, "target_attainment": 1.0},
            "V3_02": {"delivered": [8], "target": 8, "target_attainment": 1.0},
            "V3_03": {"delivered": [7], "target": 8, "target_attainment": 0.875},
            "V3_04": {"delivered": [6], "target": 5, "target_attainment": 1.0},
            "V3_05": {"delivered": [5], "target": 8, "target_attainment": 0.625},
            "V3_06": {"delivered": [4], "target": 4, "target_attainment": 1.0},
            "V3_07": {"delivered": [2], "target": 8, "target_attainment": 0.25},
            "V3_08": {"delivered": [1], "target": 8, "target_attainment": 0.125},
        },
        "regression": {"max_failures_delta": 0, "target_margin": 0.0351},
    }
    payload.update(overrides)
    return payload


class ReportGateProbeTest(unittest.TestCase):
    def _args(self, tmp: Path, baseline: Path, matrix_dir: Path, extra=None):
        args = [
            "--bundle", str(FIXTURES / "synthetic_bundle.json"),
            "--matrix", str(matrix_dir.parent),
            "--matrix-stamp", matrix_dir.name.replace("scenario-matrix-", ""),
            "--labels", str(REPO / "eval" / "frozen" / "v3" / "labels.json"),
            "--scenarios", str(REPO / "eval" / "frozen" / "v3" / "scenarios.json"),
            "--manifest", str(REPO / "eval" / "frozen" / "v3" / "MANIFEST.json"),
            "--mode", "verify",
            "--baseline", str(baseline),
        ]
        return args + list(extra or [])

    def _matrix(self, tmp: Path, mutate) -> Path:
        payload = json.loads((FIXTURES / "matrix" / "scenario-matrix-test" / "matrix.json").read_text(encoding="utf-8"))
        mutate(payload)
        directory = tmp / "scenario-matrix-audit"
        directory.mkdir()
        (directory / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return directory

    def _baseline(self, tmp: Path, payload=None) -> Path:
        path = tmp / "BASELINE.json"
        path.write_text(json.dumps(payload or _baseline_payload(), ensure_ascii=False), encoding="utf-8")
        return path

    def test_clean_run_passes(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.assertEqual(report.main(self._args(tmp, self._baseline(tmp), self._matrix(tmp, lambda p: None))), 0)

    def test_single_scenario_total_failure_fails(self):
        def mutate(payload):
            for scenario in payload["scenarios"]:
                if scenario["key"] == "V3_01":
                    scenario["runs"][0]["delivered"] = 0
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.assertEqual(report.main(self._args(tmp, self._baseline(tmp), self._matrix(tmp, mutate))), 1)

    def test_failure_increment_fails(self):
        def mutate(payload):
            for scenario in payload["scenarios"]:
                if scenario["key"] == "V3_01":
                    scenario["runs"][0]["run_status"] = "运行失败"
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.assertEqual(report.main(self._args(tmp, self._baseline(tmp), self._matrix(tmp, mutate))), 1)

    def test_negative_assertion_failure_fails(self):
        def mutate(payload):
            for scenario in payload["scenarios"]:
                if scenario["key"] == "V3_09":
                    scenario["expectation_ok"] = False
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            self.assertEqual(report.main(self._args(tmp, self._baseline(tmp), self._matrix(tmp, mutate))), 1)

    def test_v1_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            baseline = tmp / "BASELINE.json"
            baseline.write_text(json.dumps({"delivery_avg": 4.0, "failures": 0}), encoding="utf-8")
            self.assertEqual(report.main(self._args(tmp, baseline, self._matrix(tmp, lambda p: None))), 1)

    def test_baseline_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            payload = _baseline_payload(labels_sha256="deadbeef")
            self.assertEqual(report.main(self._args(tmp, self._baseline(tmp, payload), self._matrix(tmp, lambda p: None))), 1)

    def test_publish_requires_cost_and_judge(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            args = self._args(tmp, self._baseline(tmp), self._matrix(tmp, lambda p: None)) + ["--publish"]
            self.assertEqual(report.main(args), 1)

    def test_target_attainment_is_capacity_normalized(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            out = tmp / "report.json"
            args = self._args(tmp, self._baseline(tmp), self._matrix(tmp, lambda p: None)) + ["--json", str(out)]
            self.assertEqual(report.main(args), 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            # 交付按 target 截断：V3_04 交付 6 但 target=5，合计 40 / 57
            self.assertAlmostEqual(result["delivery"]["target_attainment"], 40 / 57, places=3)
            self.assertIn("target_ci95", result["delivery"])
            self.assertIn("pass_power_target", result["delivery"])


class FreezeGuardProbeTest(unittest.TestCase):
    def test_multiline_insert_is_detected(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory / "supply.sql").write_text(
                "INSERT\nINTO `member_profile`\nVALUES (1, 2, 'x');\n", encoding="utf-8")
            self.assertTrue(freeze_lib.find_supply_writes(directory))
            self.assertTrue(check_freeze.scan_eval_sql(directory))

    def test_missing_eval_sql_dir_fails(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertTrue(check_freeze.scan_eval_sql(Path(name) / "missing"))

    def test_manifest_base_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name) / "frozen"
            base.mkdir()
            for filename in ("scenarios.json", "labels.json", "MANIFEST.json"):
                (base / filename).write_bytes((REPO / "eval" / "frozen" / "v3" / filename).read_bytes())
            manifest = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
            manifest["pool"]["base_sql_sha256"] = "deadbeef"
            (base / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(check_freeze.check_manifest(base, REPO))

    def test_manifest_pool_digest_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name) / "frozen"
            base.mkdir()
            for filename in ("scenarios.json", "labels.json", "MANIFEST.json"):
                (base / filename).write_bytes((REPO / "eval" / "frozen" / "v3" / filename).read_bytes())
            manifest = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
            manifest["pool"]["pool_digest"] = "deadbeef"
            (base / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(check_freeze.check_manifest(base, REPO))


class StatsHelpersTest(unittest.TestCase):
    def test_wilson_ci_for_small_samples(self):
        result = metrics.wilson_ci(30, 30)
        self.assertEqual(result["rate"], 1.0)
        self.assertGreaterEqual(result["lo"], 0.85)
        self.assertLessEqual(result["hi"], 1.0)
        self.assertEqual(metrics.wilson_ci(0, 0)["n"], 0)

    def test_p95_interpolates(self):
        self.assertAlmostEqual(metrics.p95([1, 2, 3, 4, 5, 6, 7, 8]), 7.65, places=2)
        self.assertEqual(metrics.p95([]), 0.0)

    def test_pass_power_uses_all_subsets(self):
        groups = [[True, True, False], [True, True, True]]
        result = metrics.pass_power(groups, ks=(2, 3))
        self.assertEqual(result["pass^2"], 0.5)
        self.assertEqual(result["pass^3"], 0.5)

    def test_paired_mde(self):
        self.assertGreater(metrics.mde_paired([1, 2, 3, 4]), 0)
        self.assertEqual(metrics.mde_paired([1]), float("inf"))
        self.assertEqual(metrics.mde_paired([1, 1, 1]), 0.0)


if __name__ == "__main__":
    unittest.main()