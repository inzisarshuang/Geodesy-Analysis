"""Tests for deterministic GAMMA baseline execution plans."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.baseline_selection.gamma.models import GammaBaselineCase
from geodesy_analysis.insar.baseline_selection.gamma.plan import (
    build_gamma_baseline_plan,
)


class GammaBaselinePlanTests(unittest.TestCase):
    """Pin selected assets, inventories, and legacy-equivalent argv."""

    def _manifest(self, root: Path) -> Path:
        stack = root / "PRE" / "RSLC"
        data = stack / "RSLC"
        data.mkdir(parents=True)
        dates = ("20231214", "20231226", "20240107")
        assets = []
        for date in dates:
            slc = data / f"{date}.rslc"
            par = data / f"{date}.rslc.par"
            slc.write_bytes(b"complex")
            par.write_text("range_samples: 10\nazimuth_lines: 4\n", encoding="utf-8")
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": str(slc.relative_to(stack)),
                    "parameter_path": str(par.relative_to(stack)),
                }
            )
        manifest = stack / "registered_stack.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "sensor": "sentinel1",
                    "backend": {"name": "gamma"},
                    "geometry_type": "radar_grid",
                    "reference_date": "20231226",
                    "dates": list(dates),
                    "polarizations": ["VV"],
                    "assets": assets,
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def _case(self, root: Path, mode: str) -> GammaBaselineCase:
        return GammaBaselineCase(
            name=mode.lower(),
            project_root=root,
            registered_stack=self._manifest(root),
            polarization="VV",
            network_type=mode,
            max_perpendicular_baseline=300.0,
            max_temporal_baseline=100.0,
            output_dir=root / "ANALYSIS" / mode,
        )

    def test_builds_deterministic_inventory_from_manifest_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = build_gamma_baseline_plan(self._case(root, "SBAS"))
            self.assertEqual(plan.stack.reference_date, "20231226")
            self.assertEqual(
                [asset.date for asset in plan.stack.assets],
                ["20231214", "20231226", "20240107"],
            )
            self.assertEqual(plan.images_text, "20231214\n20231226\n20240107\n")
            self.assertEqual(
                plan.slc_tab_text,
                "".join(
                    f"{root / 'PRE/RSLC/RSLC' / date}.rslc "
                    f"{root / 'PRE/RSLC/RSLC' / date}.rslc.par\n"
                    for date in ("20231214", "20231226", "20240107")
                ),
            )
            self.assertEqual(plan.expected_network_name, "baseline_select_SBAS")
            self.assertFalse(plan.case.output_dir.exists())

    def test_builds_legacy_equivalent_base_calc_commands(self) -> None:
        expected = {
            "DSI": (
                "base_calc", "SLC_tab", "REF", "Berp_SC", "itab_SC",
                "1", "1", "-", "10000", "-", "10000", "-",
            ),
            "SBAS": (
                "base_calc", "SLC_tab", "REF", "Berp_SC", "itab_SC",
                "1", "1", "-", "300", "-", "100", "-",
            ),
            "PSI": (
                "base_calc", "SLC_tab", "REF", "Berp_SC", "itab_SC",
                "0", "1", "-", "-", "-", "-", "-",
            ),
        }
        for mode, template in expected.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = build_gamma_baseline_plan(self._case(root, mode))
                reference = str(root / "PRE/RSLC/RSLC/20231226.rslc.par")
                self.assertEqual(
                    plan.base_calc_command,
                    tuple(reference if value == "REF" else value for value in template),
                )
                self.assertEqual(plan.expected_network_name, f"baseline_select_{mode}")


if __name__ == "__main__":
    unittest.main()
