import importlib
import json
import os
import pkgutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from decimal import Decimal, localcontext
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import smartlect
from smartlect.app import health
from smartlect.config import Settings
from smartlect.money import to_cents


class FoundationTests(unittest.TestCase):
    def test_installed_package_and_mock_entry(self):
        for module in pkgutil.walk_packages(smartlect.__path__, "smartlect."):
            importlib.import_module(module.name)
        with patch.dict(os.environ, {}, clear=True):
            result = subprocess.run([sys.executable, "-m", "smartlect.app", "--check"],
                                    capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["model_mode"], "mock")
        self.assertTrue(json.loads(result.stdout)["model_ready"])
        with patch.dict(os.environ, {"SMARTLECT_MODEL_MODE": "llm"}):
            with self.assertRaises(ValueError):
                Settings.from_env()
        live = health(Settings(model_mode="live"), {})
        self.assertEqual((live["status"], live["model_ready"]), ("misconfigured", False))
        ready = health(Settings(model_mode="live"), {
            "SMARTLECT_MODEL_API_KEY": "k", "SMARTLECT_MODEL_BASE_URL": "https://example"})
        self.assertEqual((ready["status"], ready["model_ready"]), ("ok", True))

    def test_exact_amounts_and_absent_ratios(self):
        self.assertEqual(to_cents("90.00"), 9000)
        self.assertEqual(to_cents(Decimal("0.29")), 29)
        for invalid in (0.29, "NaN", "Infinity", "-0.01", "0.001", "invalid",
                        "100000000000000000000000000000.001"):
            with self.assertRaises(ValueError):
                to_cents(invalid)

    def test_http_health_from_outside_project(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "SMARTLECT_ASSISTANT_HOST": "127.0.0.1",
               "SMARTLECT_ASSISTANT_PORT": str(port), "SMARTLECT_MODEL_MODE": "mock",
               "SMARTLECT_INTERNAL_TOKEN": "fixture-internal"}
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, "-I", "-m", "smartlect.app"],
                                       cwd=directory, env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                            result = json.load(response)
                        break
                    except (URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            self.fail("assistant health did not become available")
                        time.sleep(0.02)
                self.assertEqual(result["service"], "smartlect-assistant")
                self.assertEqual(result["phase"], "F4")
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"http://127.0.0.1:{port}/recommend", timeout=0.5)
                self.assertEqual(error.exception.code, 404)
                with self.assertRaises(HTTPError) as error:
                    urlopen(f"http://127.0.0.1:{port}/internal/ledger/summary", timeout=0.5)
                self.assertEqual(error.exception.code, 404)
            finally:
                process.terminate()
                process.wait(timeout=5)

if __name__ == "__main__":
    unittest.main()
