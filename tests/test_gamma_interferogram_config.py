"""Tests for strict GAMMA interferogram project configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.interferogram_generation.gamma.config import (
    load_gamma_interferogram_config,
    select_gamma_interferogram_case,
)


class GammaInterferogramConfigTests(unittest.TestCase):
    """Pin defaults, validation, path safety, and case selection."""

    def _inputs(self, root: Path) -> None:
        for relative in (
            "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
            "TOPOGRAPHY/cop30/GAMMA/cop30.dem",
            "TOPOGRAPHY/cop30/GAMMA/cop30.dem.par",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("input\n", encoding="utf-8")

    def _write(self, root: Path, body: str) -> Path:
        path = root / "config/analysis/gamma_interferogram.cfg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        geocoding = root / "config/analysis/geocoding.cfg"
        geocoding.write_text(
            f"""[project]
root = {root}
[case:ascending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
output_dir = S1/ASCENDING_128/ANALYSIS/GEO/GAMMA
[case:descending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
output_dir = S1/DESCENDING_135/ANALYSIS/GEO/GAMMA
""",
            encoding="utf-8",
        )
        return path

    def _body(self, root: Path) -> str:
        return f"""
[project]
root = {root}

[case:ascending]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
baseline_manifest = S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json
geocoding_config = config/analysis/geocoding.cfg
polarization = vv
range_looks = 10
azimuth_looks = 2
spectral_filter = auto
output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA
"""

    def test_method_root_defaults_science_geocoding_and_flat_figure_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "S1/ASCENDING_128/GAMMA/RSLC/SUBSET/registered_stack.json",
                "S1/ASCENDING_128/GAMMA/BASELINE/baseline_manifest.json",
                "TOPOGRAPHY/cop30/GAMMA/cop30.dem",
                "TOPOGRAPHY/cop30/GAMMA/cop30.dem.par",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("input\n", encoding="utf-8")
            config = self._write(
                root,
                f"""[project]
root = {root}
[case:ascending]
project = S1/ASCENDING_128
processing_root = S1/ASCENDING_128/GAMMA
registered_stack = S1/ASCENDING_128/GAMMA/RSLC/SUBSET/registered_stack.json
baseline_manifest = S1/ASCENDING_128/GAMMA/BASELINE/baseline_manifest.json
geocoding_config = config/analysis/geocoding.cfg
polarization = VV
range_looks = 10
azimuth_looks = 2
""",
            )
            (root / "config/analysis/geocoding.cfg").write_text(
                f"""[project]
root = {root}
[case:ascending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
""",
                encoding="utf-8",
            )

            (case,) = load_gamma_interferogram_config(config, case_name="ascending")

            self.assertEqual(case.output_dir, root / "S1/ASCENDING_128/GAMMA/INTF")
            self.assertEqual(case.geocoding.output_dir, root / "S1/ASCENDING_128/GAMMA/GEOCODING")
            self.assertEqual(case.visualization_dir, root / "S1/ASCENDING_128/GAMMA/FIGURES/INTF")

    def test_loads_required_values_and_legacy_advanced_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            (case,) = load_gamma_interferogram_config(
                self._write(root, self._body(root))
            )
            self.assertEqual(case.name, "ascending")
            self.assertEqual(case.case_id, "S1/ASCENDING_128")
            self.assertEqual(case.polarization, "VV")
            self.assertEqual((case.range_looks, case.azimuth_looks), (10, 2))
            self.assertEqual(case.spectral_filter, "auto")
            self.assertEqual(
                (case.create_offset_range_start, case.create_offset_azimuth_start),
                (0, 0),
            )
            self.assertEqual(
                (case.create_offset_range_window, case.create_offset_azimuth_window),
                (32, 32),
            )
            self.assertEqual(
                (case.create_offset_range_search, case.create_offset_azimuth_search),
                (64, 64),
            )
            self.assertEqual(case.create_offset_correlation_threshold, 0.35)
            self.assertEqual(
                (case.coherence_range_window, case.coherence_azimuth_window),
                (5, 5),
            )
            self.assertEqual(case.coherence_estimator, 2)
            self.assertEqual(
                case.output_dir,
                (root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA").resolve(),
            )
            self.assertEqual(
                case.geocoding.output_dir,
                (root / "S1/ASCENDING_128/ANALYSIS/GEO/GAMMA").resolve(),
            )
            self.assertEqual(
                case.visualization_dir,
                (
                    root
                    / "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA"
                ).resolve(),
            )

    def test_science_geocoding_and_visualization_directories_are_customizable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            config_path = self._write(
                root,
                self._body(root)
                + "visualization_dir = S1/ASCENDING_128/VISUALIZATION/manual_ifg\n",
            )
            geocoding_config = root / "config/analysis/geocoding.cfg"
            geocoding_config.write_text(
                f"""[project]
root = {root}
[case:ascending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
output_dir = results/custom_geo
""",
                encoding="utf-8",
            )
            (case,) = load_gamma_interferogram_config(config_path)
            self.assertEqual(
                case.geocoding.output_dir,
                (root / "results/custom_geo").resolve(),
            )
            self.assertEqual(
                case.visualization_dir,
                (root / "S1/ASCENDING_128/VISUALIZATION/manual_ifg").resolve(),
            )

            external = Path(directory).parent / "custom-science"
            body = self._body(root).replace(
                "output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                f"output_dir = {external}",
            )
            config_path.write_text(body, encoding="utf-8")
            (case,) = load_gamma_interferogram_config(config_path)
            self.assertEqual(case.output_dir, external.resolve())

            geo_config = root / "config/analysis/geocoding.cfg"
            geo_config.write_text(
                f"""[project]
root = {root}
[case:ascending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA
""",
                encoding="utf-8",
            )
            config_path.write_text(self._body(root), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output directories overlap"):
                load_gamma_interferogram_config(config_path)

    def test_all_outputs_accept_distinct_absolute_paths_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            output_root = Path(external)
            self._inputs(root)
            geo_config = root / "config/analysis/geocoding.cfg"
            geo_config.parent.mkdir(parents=True, exist_ok=True)
            geo_config.write_text(
                f"""[project]
root = {root}
[case:ascending]
dem = TOPOGRAPHY/cop30/GAMMA/cop30.dem
dem_par = TOPOGRAPHY/cop30/GAMMA/cop30.dem.par
output_dir = {output_root / "geometry"}
""",
                encoding="utf-8",
            )
            body = (
                self._body(root).replace(
                    "output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                    f"output_dir = {output_root / 'science'}",
                )
            )
            config_path = root / "config/analysis/gamma_interferogram.cfg"
            config_path.write_text(body, encoding="utf-8")
            (case,) = load_gamma_interferogram_config(config_path)
            self.assertEqual(case.geocoding.output_dir, output_root / "geometry")
            self.assertEqual(case.output_dir, output_root / "science")

    def test_case_values_override_defaults_and_modes_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            config = self._write(
                root,
                f"""
[project]
root = {root}
[defaults]
polarization = HH
range_looks = 4
azimuth_looks = 3
spectral_filter = on
create_offset_range_start = -2
create_offset_azimuth_start = 7
create_offset_range_window = 48
create_offset_azimuth_window = 24
create_offset_range_search = 96
create_offset_azimuth_search = 40
create_offset_correlation_threshold = 0.6
coherence_range_window = 7
coherence_azimuth_window = 9
coherence_estimator = 1
[case:ascending]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
baseline_manifest = S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json
geocoding_config = config/analysis/geocoding.cfg
polarization = vv
spectral_filter = OFF
output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA
""",
            )
            (case,) = load_gamma_interferogram_config(config)
            self.assertEqual(case.polarization, "VV")
            self.assertEqual(case.spectral_filter, "off")
            self.assertEqual((case.range_looks, case.azimuth_looks), (4, 3))
            self.assertEqual(
                (case.create_offset_range_start, case.create_offset_azimuth_start),
                (-2, 7),
            )
            self.assertEqual(
                (case.create_offset_range_window, case.create_offset_azimuth_window),
                (48, 24),
            )
            self.assertEqual(
                (case.create_offset_range_search, case.create_offset_azimuth_search),
                (96, 40),
            )
            self.assertEqual(case.create_offset_correlation_threshold, 0.6)
            self.assertEqual(
                (case.coherence_range_window, case.coherence_azimuth_window), (7, 9)
            )
            self.assertEqual(case.coherence_estimator, 1)

    def test_accepts_full_rslc_stack_when_no_subset_stack_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            full_stack = root / "S1/ASCENDING_128/PRE/GAMMA/RSLC/registered_stack.json"
            full_stack.parent.mkdir(parents=True)
            full_stack.write_text("input\n", encoding="utf-8")
            body = self._body(root).replace(
                "PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
                "PRE/GAMMA/RSLC/registered_stack.json",
            )

            (case,) = load_gamma_interferogram_config(self._write(root, body))

            self.assertEqual(case.registered_stack, full_stack.resolve())

    def test_rejects_missing_required_unknown_and_invalid_values(self) -> None:
        replacements = (
            ("range_looks = 10", "", "missing keys"),
            ("range_looks = 10", "range_looks = 0", "positive integer"),
            ("azimuth_looks = 2", "azimuth_looks = one", "positive integer"),
            ("spectral_filter = auto", "spectral_filter = maybe", "auto, on, or off"),
            (
                "output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                "output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA\nsurprise = 1",
                "unknown key",
            ),
        )
        advanced = """
[defaults]
create_offset_range_window = 32
create_offset_azimuth_window = 32
create_offset_range_search = 64
create_offset_azimuth_search = 64
create_offset_correlation_threshold = 0.35
coherence_range_window = 5
coherence_azimuth_window = 5
coherence_estimator = 2
"""
        for old, new, message in replacements:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._inputs(root)
                body = self._body(root).replace(old, new)
                config = self._write(root, body)
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_interferogram_config(config)

        invalid_advanced = (
            ("create_offset_range_window = 32", "create_offset_range_window = 0", "positive integer"),
            ("create_offset_azimuth_window = 32", "create_offset_azimuth_window = -1", "positive integer"),
            ("create_offset_range_search = 64", "create_offset_range_search = 0", "positive integer"),
            ("create_offset_azimuth_search = 64", "create_offset_azimuth_search = no", "positive integer"),
            ("create_offset_correlation_threshold = 0.35", "create_offset_correlation_threshold = 1.1", r"\[0, 1\]"),
            ("coherence_range_window = 5", "coherence_range_window = 0", "positive integer"),
            ("coherence_azimuth_window = 5", "coherence_azimuth_window = 0", "positive integer"),
            ("coherence_estimator = 2", "coherence_estimator = 0", "positive integer"),
        )
        for old, new, message in invalid_advanced:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._inputs(root)
                body = self._body(root).replace(
                    "[case:ascending]", advanced.replace(old, new) + "\n[case:ascending]"
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_interferogram_config(self._write(root, body))

    def test_rejects_paths_outside_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            self._inputs(root)
            outside_path = Path(outside) / "stack.json"
            outside_path.write_text("outside\n", encoding="utf-8")
            for key, old in (
                (
                    "registered_stack",
                    "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
                ),
                (
                    "baseline_manifest",
                    "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
                ),
            ):
                with self.subTest(key=key):
                    config = self._write(
                        root, self._body(root).replace(f"{key} = {old}", f"{key} = {outside_path}")
                    )
                    with self.assertRaisesRegex(ValueError, "case input.*case root"):
                        load_gamma_interferogram_config(config)

    def test_rejects_missing_and_cross_case_inputs_but_accepts_custom_output(self) -> None:
        replacements = (
            ("case_root = S1/ASCENDING_128\n", "", "missing keys.*case_root"),
            (
                "baseline_manifest = S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
                "baseline_manifest = S1/DESCENDING_135/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
                "case input.*case root",
            ),
        )
        for old, new, message in replacements:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._inputs(root)
                config = self._write(root, self._body(root).replace(old, new))
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_interferogram_config(config)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            (case,) = load_gamma_interferogram_config(
                self._write(
                    root,
                    self._body(root).replace(
                        "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                        "custom/results/interferogram",
                    ),
                )
            )
            self.assertEqual(case.output_dir, (root / "custom/results/interferogram").resolve())

    def test_rejects_input_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(directory)
            self._inputs(root)
            height = root / "TOPOGRAPHY/cop30/GAMMA/cop30.dem"
            height.unlink()
            outside = Path(outside_dir) / "cop30.dem"
            outside.write_bytes(b"dem")
            height.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "project input.*project root"):
                load_gamma_interferogram_config(self._write(root, self._body(root)))

    def test_select_requires_case_for_multiple_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            second = self._body(root).replace("[case:ascending]", "[case:descending]")
            config = self._write(root, self._body(root) + second.split("[project]", 1)[1].split("\n", 2)[2])
            cases = load_gamma_interferogram_config(config)
            with self.assertRaisesRegex(ValueError, "--case is required"):
                select_gamma_interferogram_case(cases, None)
            self.assertEqual(select_gamma_interferogram_case(cases, "descending").name, "descending")
            with self.assertRaisesRegex(ValueError, "unknown case"):
                select_gamma_interferogram_case(cases, "missing")

    def test_loading_requested_case_ignores_invalid_other_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            config = self._write(
                root,
                self._body(root)
                + """
[case:unused]
case_root = S1/DESCENDING_135
registered_stack = S1/DESCENDING_135/missing.json
""",
            )
            (case,) = load_gamma_interferogram_config(
                config, case_name="ascending"
            )
            self.assertEqual(case.name, "ascending")

            with self.assertRaisesRegex(ValueError, "missing keys"):
                load_gamma_interferogram_config(config, case_name="unused")


if __name__ == "__main__":
    unittest.main()
