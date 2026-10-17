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
            "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("input\n", encoding="utf-8")

    def _write(self, root: Path, body: str) -> Path:
        path = root / "config/analysis/gamma_interferogram.cfg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def _body(self, root: Path) -> str:
        return f"""
[project]
root = {root}

[case:ascending]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
baseline_manifest = S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json
polarization = vv
range_looks = 10
azimuth_looks = 2
radar_height = S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim
spectral_filter = auto
output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA
"""

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
                case.visualization_dir,
                (root / "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA").resolve(),
            )

    def test_explicit_visualization_directory_is_case_confined_and_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            body = self._body(root) + "visualization_dir = S1/ASCENDING_128/VISUALIZATION/manual_ifg\n"
            (case,) = load_gamma_interferogram_config(self._write(root, body))
            self.assertEqual(
                case.visualization_dir,
                (root / "S1/ASCENDING_128/VISUALIZATION/manual_ifg").resolve(),
            )

            for value in (
                "S1/DESCENDING_135/VISUALIZATION/GAMMA",
                "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                "S1/ASCENDING_128/PRE/GAMMA",
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_gamma_interferogram_config(
                        self._write(
                            root,
                            self._body(root)
                            + f"visualization_dir = {value}\n",
                        )
                    )

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
polarization = vv
radar_height = S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim
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
                (
                    "radar_height",
                    "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
                ),
            ):
                with self.subTest(key=key):
                    config = self._write(
                        root, self._body(root).replace(f"{key} = {old}", f"{key} = {outside_path}")
                    )
                    with self.assertRaisesRegex(ValueError, "case input.*case root"):
                        load_gamma_interferogram_config(config)

    def test_rejects_missing_cross_case_and_noncanonical_paths(self) -> None:
        replacements = (
            ("case_root = S1/ASCENDING_128\n", "", "missing keys.*case_root"),
            (
                "baseline_manifest = S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
                "baseline_manifest = S1/DESCENDING_135/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
                "case input.*case root",
            ),
            (
                "radar_height = S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
                "radar_height = S1/DESCENDING_135/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
                "case input.*case root",
            ),
            (
                "output_dir = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
                "output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/OTHER",
                "canonical interferogram output",
            ),
        )
        for old, new, message in replacements:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._inputs(root)
                config = self._write(root, self._body(root).replace(old, new))
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_interferogram_config(config)

    def test_rejects_input_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._inputs(root)
            height = root / "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim"
            height.unlink()
            outside = root / "outside.hgt"
            outside.write_bytes(b"height")
            height.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "case input.*case root"):
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


if __name__ == "__main__":
    unittest.main()
