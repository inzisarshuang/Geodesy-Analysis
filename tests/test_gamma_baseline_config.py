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
        manifest = (
            root
            / "S1"
            / "ASCENDING_128"
            / "PRE"
            / "GAMMA"
            / "RSLC_SUBSET"
            / "registered_stack.json"
        )
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

[case:main]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
network_type = psi
max_temporal_baseline = 40
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
""",
            )
            (case,) = load_gamma_baseline_config(config)
            self.assertEqual(case.name, "main")
            self.assertEqual(case.case_id, "S1/ASCENDING_128")
            self.assertEqual(case.case_root, (root / "S1/ASCENDING_128").resolve())
            self.assertEqual(case.project_root, root.resolve())
            self.assertEqual(case.network_type, "PSI")
            self.assertEqual(case.max_perpendicular_baseline, 300.0)
            self.assertEqual(case.max_temporal_baseline, 40.0)
            self.assertEqual(case.polarization, "VV")
            self.assertEqual(
                case.registered_stack,
                (
                    root
                    / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json"
                ).resolve(),
            )
            self.assertEqual(
                case.output_dir,
                (root / "S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE").resolve(),
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
case_root = S1/ASCENDING_128
registered_stack = {manifest}
polarization = vv
network_type = {mode}
max_perpendicular_baseline = 250
max_temporal_baseline = 80
output_dir = {root / 'S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE'}
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
            (
                "output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE",
                "output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE\nsurprise = 1",
                "unknown key",
            ),
        )
        for original, replacement, message in bad_values:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._project(root)
                body = f"""
[project]
root = {root}
[case:main]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
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
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
""",
            )
            with self.assertRaisesRegex(ValueError, "unsafe or empty case name"):
                load_gamma_baseline_config(config)

    def test_rejects_duplicate_sections_and_unsupported_sections(self) -> None:
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

    def test_rejects_missing_invalid_or_cross_case_contract_paths(self) -> None:
        template = """
[project]
root = {root}
[case:main]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
"""
        replacements = (
            ("case_root = S1/ASCENDING_128\n", "", "missing keys.*case_root"),
            ("S1/ASCENDING_128", "S1/ascending_128", "uppercase POSIX"),
            (
                "registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
                "registered_stack = S1/DESCENDING_135/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
                "case input.*case root",
            ),
            (
                "output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE",
                "output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/OTHER",
                "canonical baseline output",
            ),
        )
        for original, replacement, message in replacements:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._project(root)
                config = self._write(
                    root, template.format(root=root).replace(original, replacement)
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_baseline_config(config)

    def test_rejects_output_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            case = root / "S1/ASCENDING_128"
            outside = root / "outside"
            outside.mkdir()
            (case / "ANALYSIS").symlink_to(outside, target_is_directory=True)
            config = self._write(
                root,
                f"""
[project]
root = {root}
[case:main]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
polarization = VV
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
""",
            )
            with self.assertRaisesRegex(ValueError, "case output.*case root"):
                load_gamma_baseline_config(config)

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
case_root = S1/ASCENDING_128
registered_stack = {manifest}
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
[case:b]
case_root = S1/ASCENDING_128
registered_stack = {manifest}
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 100
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
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
