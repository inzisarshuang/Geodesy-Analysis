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
from geodesy_analysis.insar.filtering.config import load_filtering_config
from geodesy_analysis.insar.unwrapping.gamma.mcf.config import load_gamma_mcf_config
from geodesy_analysis.insar.detrending.gamma.quad.config import (
    load_gamma_quad_detrend_config,
)


class ConfigExampleTests(unittest.TestCase):
    """Keep examples aligned with the formal project/case contract."""

    repository = Path(__file__).resolve().parents[1]

    def _write_example(self, root: Path, name: str) -> Path:
        source = self.repository / "config_examples/analysis" / name
        text = source.read_text(encoding="utf-8").replace(
            "/path/to/research-project", str(root)
        )
        target = root / "S1/ASCENDING_128/config/analysis" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _write_geocoding_example(self, root: Path) -> Path:
        source = self.repository / "config_examples/analysis/gamma_geocoding.cfg"
        text = source.read_text(encoding="utf-8").replace(
            "/path/to/research-project", str(root)
        )
        target = root / "config/analysis/gamma_geocoding.cfg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _inputs(self, root: Path) -> None:
        for relative in (
            "S1/ASCENDING_128/GAMMA/RSLC/SUBSET/registered_stack.json",
            "S1/ASCENDING_128/GAMMA/BASELINE/baseline_manifest.json",
            "S1/ASCENDING_128/GAMMA/INTF/interferogram_manifest.json",
            "S1/ASCENDING_128/GAMMA/FILTERING/NL_INSAR/filtering_manifest.json",
            "S1/ASCENDING_128/GAMMA/UNW/GAMMA_MCF/unwrapping_manifest.json",
            "TOPOGRAPHY/jishishan_cop30/GAMMA/jishishan_cop30.dem",
            "TOPOGRAPHY/jishishan_cop30/GAMMA/jishishan_cop30.dem.par",
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
            filtering_cfg = self._write_example(root, "insar_filtering.cfg")
            mcf_cfg = self._write_example(root, "gamma_mcf_unwrapping.cfg")
            quad_cfg = self._write_example(root, "gamma_quad_detrending.cfg")
            self._write_geocoding_example(root)
            previous = Path.cwd()
            try:
                os.chdir(cwd)
                (baseline,) = load_gamma_baseline_config(baseline_cfg)
                (interferogram,) = load_gamma_interferogram_config(interferogram_cfg)
                filtering = load_filtering_config(filtering_cfg)
                (mcf,) = load_gamma_mcf_config(mcf_cfg)
                (quad,) = load_gamma_quad_detrend_config(quad_cfg)
            finally:
                os.chdir(previous)

            self.assertEqual(baseline.name, "main")
            self.assertEqual(baseline.case_id, "S1/ASCENDING_128")
            self.assertIn("SUBSET", baseline.registered_stack.parts)
            self.assertEqual(
                baseline.output_dir,
                root / "S1/ASCENDING_128/GAMMA/BASELINE",
            )
            self.assertEqual(interferogram.name, "main")
            self.assertEqual(interferogram.case_id, "S1/ASCENDING_128")
            self.assertEqual(
                interferogram.geocoding.output_dir,
                root / "S1/ASCENDING_128/GAMMA/GEOCODING",
            )
            self.assertEqual(
                interferogram.visualization_dir,
                root / "S1/ASCENDING_128/GAMMA/FIGURES/INTF",
            )
            self.assertEqual(
                interferogram.output_dir,
                root / "S1/ASCENDING_128/GAMMA/INTF",
            )
            self.assertEqual(
                interferogram.geocoding.output_dir,
                root / "S1/ASCENDING_128/GAMMA/GEOCODING",
            )
            self.assertFalse((root / "S1/ASCENDING_128/LOG").exists())
            self.assertEqual(
                [case.output_dir for case in filtering],
                [
                    root / f"S1/ASCENDING_128/GAMMA/FILTERING/{method}"
                    for method in ("NL_INSAR", "GAMMA_BM3D", "GAMMA_ADF")
                ],
            )
            self.assertEqual(
                mcf.output_dir, root / "S1/ASCENDING_128/GAMMA/UNW/GAMMA_MCF"
            )
            self.assertEqual(
                quad.output_dir,
                root / "S1/ASCENDING_128/GAMMA/DETRENDING/GAMMA_QUAD",
            )

    def test_examples_document_stage_owned_flat_quicklooks(self) -> None:
        baseline = (self.repository / "config_examples/analysis/gamma_baseline.cfg").read_text(
            encoding="utf-8"
        )
        interferogram = (
            self.repository / "config_examples/analysis/gamma_interferogram.cfg"
        ).read_text(encoding="utf-8")
        geocoding = (
            self.repository / "config_examples/analysis/gamma_geocoding.cfg"
        ).read_text(encoding="utf-8")
        filtering = (
            self.repository / "config_examples/analysis/insar_filtering.cfg"
        ).read_text(encoding="utf-8")
        mcf = (
            self.repository / "config_examples/analysis/gamma_mcf_unwrapping.cfg"
        ).read_text(encoding="utf-8")
        combined = baseline + interferogram + geocoding + filtering + mcf

        self.assertIn("project = S1/ASCENDING_128", baseline)
        self.assertIn("processing_root = S1/ASCENDING_128/GAMMA", combined)
        self.assertIn("RSLC/SUBSET", combined)
        self.assertIn("output_dir/MLI", interferogram)
        self.assertIn("output_dir/PAIRS", interferogram)
        self.assertIn("GAMMA/GEOCODING", geocoding)
        self.assertIn(
            "figure_dir = S1/ASCENDING_128/GAMMA/FIGURES/INTF",
            interferogram,
        )
        for method in ("NL_INSAR", "GAMMA_BM3D", "GAMMA_ADF"):
            self.assertIn(
                f"figure_dir = S1/ASCENDING_128/GAMMA/FIGURES/FILTERING/{method}",
                filtering,
            )
        self.assertIn(
            "figure_dir = S1/ASCENDING_128/GAMMA/FIGURES/UNW/GAMMA_MCF",
            mcf,
        )
        self.assertIn(".mli.bmp", interferogram)
        self.assertIn(".phase.bmp", interferogram)
        self.assertIn(".coherence.bmp", interferogram)
        self.assertIn(".intensity.bmp", interferogram)
        self.assertIn(".tflt.filt.bmp", filtering)
        self.assertIn(".coh.filt.bmp", filtering)
        self.assertIn(".tflt.filt.unw.bmp", mcf)
        self.assertNotRegex(combined, r"VISUALIZATION/[^\n#]*/pairs/")
        self.assertNotIn("PNG", combined)


if __name__ == "__main__":
    unittest.main()
