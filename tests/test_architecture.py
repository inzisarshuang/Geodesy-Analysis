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
                self.assertNotIn("/mnt/beegfs", text)
                self.assertNotIn("/home/yilun", text)

    def test_analysis_has_no_visualization_runtime_dependency(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source_root = repository / "src"
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("matplotlib", text.lower())
                self.assertNotIn("geodesy_visualization", text)

        project = (repository / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("geodesy-analysis-baseline-plot", project)
        self.assertNotIn("matplotlib", project.lower())
        self.assertNotIn("plot =", project)
        self.assertFalse(
            (source_root / "geodesy_analysis/insar/baseline_selection/common/plot_cli.py").exists()
        )
        self.assertFalse(
            (source_root / "geodesy_analysis/insar/baseline_selection/common/plot_config.py").exists()
        )
        self.assertFalse((repository / "config_examples/baseline_plot.cfg").exists())


if __name__ == "__main__":
    unittest.main()
