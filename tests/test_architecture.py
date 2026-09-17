"""Architecture checks for the standalone Analysis source tree."""

from __future__ import annotations

import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    """Prevent sibling-source and legacy repository imports."""

    def test_production_modules_do_not_import_legacy_sibling_sources(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src"
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("from lib", text)
                self.assertNotIn("GAMMA-InSAR", text)
                self.assertNotIn("sys.path", text)


if __name__ == "__main__":
    unittest.main()
