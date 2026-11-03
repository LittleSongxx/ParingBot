import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import report
import safety_checks

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerPathsTest(unittest.TestCase):
    def test_load_suites(self):
        spec = importlib.util.spec_from_file_location("run_matrix", REPO / "eval" / "run_matrix.py")
        module = importlib.util.module_from_spec(spec)
        # 不执行 main；只验证数据文件可解析
        data_v3 = json.loads((REPO / "eval" / "frozen" / "v3" / "scenarios.json").read_text(encoding="utf-8"))
        data_demo = json.loads((REPO / "eval" / "suites" / "demo.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data_v3["scenarios"]), 10)
        self.assertEqual(len(data_demo["scenarios"]), 20)
        self.assertEqual(len([s for s in data_v3["scenarios"] if s.get("run")]), 8)


class ReportExtraGateTest(unittest.TestCase):
    def _args(self, matrix, mode="baseline"):
        return [
            "--bundle", str(FIXTURES / "synthetic_bundle.json"),
            "--matrix", str(matrix),
            "--labels", str(REPO / "eval" / "frozen" / "v3" / "labels.json"),
            "--scenarios", str(REPO / "eval" / "frozen" / "v3" / "scenarios.json"),
            "--manifest", str(REPO / "eval" / "frozen" / "v3" / "MANIFEST.json"),
            "--mode", mode,
        ]

    def test_missing_required_scenario_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "scenario-matrix-test"
            target.mkdir()
            payload = json.loads((FIXTURES / "matrix" / "scenario-matrix-test" / "matrix.json").read_text(encoding="utf-8"))
            payload["scenarios"] = [s for s in payload["scenarios"] if s["key"] != "V3_01"]
            (target / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(report.main(self._args(tmp)), 1)


class SafetySummaryTest(unittest.TestCase):
    def test_run_summary_is_scanned(self):
        bundle = {"runs": [{
            "run": {"id": 1, "summary": "保证一定合适"},
            "applicant": {"nickname": "a"},
            "candidates": [],
        }]}
        findings = safety_checks.scan_bundle(bundle)
        self.assertTrue(any(item["kind"] == "promise" for item in findings))


class HumanKappaTest(unittest.TestCase):
    def test_perfect_agreement(self):
        kappa = load_module(REPO / "eval" / "human_eval" / "kappa.py", "human_kappa")
        value, observed = kappa.kappa([(4, 4), (3, 3), (5, 5)])
        self.assertEqual(value, 1.0)
        self.assertEqual(observed, 1.0)

    def test_chance_level(self):
        kappa = load_module(REPO / "eval" / "human_eval" / "kappa.py", "human_kappa")
        value, _ = kappa.kappa([(1, 2), (2, 1)])
        self.assertLess(value, 0.1)


if __name__ == "__main__":
    unittest.main()
