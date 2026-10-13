"""Tests for strict GAMMA baseline project configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.baseline_selection.gamma.config import (
    load_gamma_baseline_config,
    select_gamma_baseline_case,
)


class GammaBaselineConfigTests(unittest.TestCase):
    """Pin cfg precedence, validation, and case selection."""

    def _project(self, root: Path) -> Path:
        manifest = root / "PRE" / "RSLC" / "registered_stack.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        return manifest

    def _write(self, root: Path, text: str) -> Path:
        config = root / "config" / "analysis" / "gamma_baseline.cfg"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(text, encoding="utf-8")
        return config

    def test_resolves_relative_paths_and_case_overrides_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            config = self._write(
                root,
                f"""
[project]
root = {root}

[defaults]
network_type = sbas
max_perpendicular_baseline = 300
max_temporal_baseline = 100
polarization = VV

[case:ascending]
registered_stack = PRE/RSLC/registered_stack.json
network_type = psi
max_temporal_baseline = 40
output_dir = ANALYSIS/GAMMA/ascending/BASELINE
""",
            )
            (case,) = load_gamma_baseline_config(config)
            self.assertEqual(case.name, "ascending")
            self.assertEqual(case.project_root, root.resolve())
            self.assertEqual(case.network_type, "PSI")
            self.assertEqual(case.max_perpendicular_baseline, 300.0)
            self.assertEqual(case.max_temporal_baseline, 40.0)
            self.assertEqual(case.polarization, "VV")
            self.assertEqual(
                case.registered_stack,
                (root / "PRE/RSLC/registered_stack.json").resolve(),
            )
            self.assertEqual(
                case.output_dir,
                (root / "ANALYSIS/GAMMA/ascending/BASELINE").resolve(),
            )

    def test_accepts_absolute_project_confined_paths_and_normalizes_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._project(root)
            sections = []
            for name, mode in (("dsi", "dsi"), ("sbas", "SBAS"), ("psi", "Psi")):
                sections.append(
                    f"""
[case:{name}]
registered_stack = {manifest}
polarization = vv
network_type = {mode}
max_perpendicular_baseline = 250
max_temporal_baseline = 80
output_dir = {root / 'ANALYSIS' / name}
"""
                )
            config = self._write(
                root,
                f"[project]\nroot = {root}\n" + "".join(sections),
            )
            cases = load_gamma_baseline_config(config)
            self.assertEqual([case.network_type for case in cases], ["DSI", "SBAS", "PSI"])
            self.assertEqual([case.polarization for case in cases], ["VV", "VV", "VV"])

    def test_rejects_invalid_thresholds_unknown_content_and_unsafe_cases(self) -> None:
        bad_values = (
            ("max_perpendicular_baseline = 300", "max_perpendicular_baseline = 0", "positive finite"),
            ("max_temporal_baseline = 100", "max_temporal_baseline = nan", "positive finite"),
            ("network_type = SBAS", "network_type = dense", "DSI, SBAS, or PSI"),
            ("output_dir = ANALYSIS/BASELINE", "output_dir = ANALYSIS/BASELINE\nsurprise = 1", "unknown key"),
        )
        for original, replacement, message in bad_values:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._project(root)
                body = f"""
[project]
root = {root}
[case:main]
registered_stack = PRE/RSLC/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = ANALYSIS/BASELINE
""".replace(original, replacement)
                config = self._write(
                    root,
                    body,
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_baseline_config(config)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            config = self._write(
                root,
                f"""
[project]
root = {root}
[case:../unsafe]
registered_stack = PRE/RSLC/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = ANALYSIS/BASELINE
""",
            )
            with self.assertRaisesRegex(ValueError, "unsafe or empty case name"):
                load_gamma_baseline_config(config)

    def test_rejects_duplicate_sections_unsupported_sections_and_output_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            duplicate = self._write(
                root,
                f"[project]\nroot={root}\n[case:main]\noutput_dir=A\n[case:main]\noutput_dir=B\n",
            )
            with self.assertRaisesRegex(ValueError, "invalid GAMMA baseline configuration"):
                load_gamma_baseline_config(duplicate)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            unsupported = self._write(
                root, f"[project]\nroot={root}\n[plot]\ndpi=300\n"
            )
            with self.assertRaisesRegex(ValueError, "unsupported section"):
                load_gamma_baseline_config(unsupported)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            overlap = self._write(
                root,
                f"""
[project]
root = {root}
[case:main]
registered_stack = PRE/RSLC/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = PRE/RSLC/ANALYSIS
""",
            )
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                load_gamma_baseline_config(overlap)

    def test_select_requires_name_for_multiple_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._project(root)
            config = self._write(
                root,
                f"""
[project]
root = {root}
[case:a]
registered_stack = {manifest}
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = ANALYSIS/A
[case:b]
registered_stack = {manifest}
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = ANALYSIS/B
""",
            )
            cases = load_gamma_baseline_config(config)
            with self.assertRaisesRegex(ValueError, "--case is required"):
                select_gamma_baseline_case(cases, None)
            self.assertEqual(select_gamma_baseline_case(cases, "b").name, "b")
            with self.assertRaisesRegex(ValueError, "unknown case"):
                select_gamma_baseline_case(cases, "missing")


if __name__ == "__main__":
    unittest.main()
