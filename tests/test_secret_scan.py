"""Synthetic checks for public-source path detection; no real account data."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/secret_scan.py"
spec = importlib.util.spec_from_file_location("repository_secret_scan", path)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class ScanCoverageTests(unittest.TestCase):
    def test_windows_home_paths_single_and_escaped(self):
        rule = dict(scan.RULES)["windows-user-path"]
        for separator in ("\\", "\\\\", "/"):
            value = "C:" + separator + "Users" + separator + "fixture-user"
            self.assertIsNotNone(rule.search(value))
        self.assertIsNone(rule.search("C:/ai-companion/tools"))

    def test_go_and_patch_files_are_scanned(self):
        self.assertTrue({".go", ".patch", ".diff"} <= scan.TEXT_EXT)


if __name__ == "__main__":
    unittest.main()
