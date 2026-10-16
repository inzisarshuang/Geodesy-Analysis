"""Executable regression gates for the public GAMMA CFG examples."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.baseline_selection.gamma.config import (
    load_gamma_baseline_config,
)
from geodesy_analysis.insar.interferogram_generation.gamma.config import (
    load_gamma_interferogram_config,
)


class ConfigExampleTests(unittest.TestCase):
    """Keep examples aligned with the formal project/case contract."""

    repository = Path(__file__).resolve().parents[1]

    def _write_example(self, root: Path, name: str) -> Path:
        source = self.repository / "config_examples" / name
        text = source.read_text(encoding="utf-8").replace(
            "/path/to/research-project", str(root)
        )
        target = root / "S1/ASCENDING_128/config/analysis" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _inputs(self, root: Path) -> None:
        for relative in (
            "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
            "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("input\n", encoding="utf-8")

    def test_examples_parse_from_an_unrelated_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as cwd:
            root = Path(project_dir)
            self._inputs(root)
            baseline_cfg = self._write_example(root, "gamma_baseline.cfg")
            interferogram_cfg = self._write_example(root, "gamma_interferogram.cfg")
            previous = Path.cwd()
            try:
                os.chdir(cwd)
                (baseline,) = load_gamma_baseline_config(baseline_cfg)
                (interferogram,) = load_gamma_interferogram_config(interferogram_cfg)
            finally:
                os.chdir(previous)

            self.assertEqual(baseline.name, "main")
            self.assertEqual(baseline.case_id, "S1/ASCENDING_128")
            self.assertIn("RSLC_SUBSET", baseline.registered_stack.parts)
            self.assertEqual(
                baseline.output_dir,
                root / "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA",
            )
            self.assertEqual(interferogram.name, "main")
            self.assertEqual(interferogram.case_id, "S1/ASCENDING_128")
            self.assertEqual(
                interferogram.output_dir,
                root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
            )
            self.assertFalse((root / "S1/ASCENDING_128/LOG").exists())

    def test_examples_document_owned_layout_without_rendering(self) -> None:
        baseline = (self.repository / "config_examples/gamma_baseline.cfg").read_text(
            encoding="utf-8"
        )
        interferogram = (
            self.repository / "config_examples/gamma_interferogram.cfg"
        ).read_text(encoding="utf-8")
        combined = baseline + interferogram

        self.assertIn("case_root = S1/ASCENDING_128", baseline)
        self.assertIn("RSLC_SUBSET", combined)
        self.assertIn("S1/ASCENDING_128/LOG/ANALYSIS/BASELINE_SELECTION/GAMMA", baseline)
        self.assertIn(
            "S1/ASCENDING_128/LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
            interferogram,
        )
        self.assertIn("output_dir/MLI", interferogram)
        self.assertIn("output_dir/PAIRS", interferogram)
        self.assertNotIn("quicklook", combined.lower())
        self.assertNotIn("PNG", combined)
        self.assertNotIn("FIGURES", combined)


if __name__ == "__main__":
    unittest.main()
