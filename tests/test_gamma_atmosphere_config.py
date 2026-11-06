"""Strict configuration tests for GAMMA atmosphere correction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.atmosphere.gamma.config import (
    load_gamma_atmosphere_config,
)


class GammaAtmosphereConfigTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "project"
        project.mkdir()
        manifest = (
            project
            / "S1/ASCENDING_128/GAMMA_mb/DETRENDING/GAMMA_QUAD/"
            "detrending_manifest.json"
        )
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        polygon = project / "config/GAMMA_mb/deformation.poly"
        polygon.parent.mkdir(parents=True)
        polygon.write_text("0 0\n1 0\n1 1\n", encoding="utf-8")
        return project

    def _write(
        self,
        root: Path,
        project: Path,
        *,
        method: str,
        extra: str = "",
        defaults: str = "",
    ) -> Path:
        cfg = root / f"{method}.cfg"
        cfg.write_text(
            f"""[project]
root = {project}

[defaults]
{defaults}

[case:ascending]
project = S1/ASCENDING_128
processing_root = S1/ASCENDING_128/GAMMA_mb
detrending_manifest = S1/ASCENDING_128/GAMMA_mb/DETRENDING/GAMMA_QUAD/detrending_manifest.json
method = {method}
{extra}
""",
            encoding="utf-8",
        )
        return cfg

    def test_method_defaults_are_method_centric_and_legacy_compatible(self) -> None:
        expected = {
            "none": ("NONE", (256, 256, 128, 128)),
            "gamma_atm_mod_2d_auto": (
                "GAMMA_ATM_MOD_2D_AUTO",
                (256, 256, 128, 128),
            ),
            "gamma_atm_mod_2d_polygon": (
                "GAMMA_ATM_MOD_2D_POLYGON",
                (16, 16, 8, 8),
            ),
            "gamma_fspf_atm_mod_2d": (
                "GAMMA_FSPF_ATM_MOD_2D",
                (8, 8, 4, 4),
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            for method, (identity, windows) in expected.items():
                extra = (
                    "polygon_file = config/GAMMA_mb/deformation.poly"
                    if method == "gamma_atm_mod_2d_polygon"
                    else ""
                )
                case = load_gamma_atmosphere_config(
                    self._write(root, project, method=method, extra=extra)
                )[0]
                self.assertEqual(case.method, method)
                self.assertEqual(
                    case.output_dir,
                    project / f"S1/ASCENDING_128/GAMMA_mb/ATMOSPHERE/{identity}",
                )
                self.assertEqual(
                    case.figure_dir,
                    project
                    / f"S1/ASCENDING_128/GAMMA_mb/FIGURES/ATMOSPHERE/{identity}",
                )
                self.assertEqual(
                    case.log_dir,
                    project
                    / f"S1/ASCENDING_128/GAMMA_mb/LOG/ANALYSIS/ATMOSPHERE/{identity}",
                )
                self.assertEqual(
                    (
                        case.fit_window_range,
                        case.fit_window_azimuth,
                        case.fit_step_range,
                        case.fit_step_azimuth,
                    ),
                    windows,
                )
                self.assertEqual(case.height_correlation_threshold, 0.1)
                self.assertTrue(case.intensity_background)
                if method == "gamma_fspf_atm_mod_2d":
                    self.assertEqual(
                        (case.fspf_mode, case.fspf_window_size, case.fspf_overlap),
                        (2, 256, 4),
                    )

    def test_explicit_paths_and_parameters_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            cfg = self._write(
                root,
                project,
                method="gamma_fspf_atm_mod_2d",
                extra="""output_dir = custom/science
figure_dir = custom/figures
log_dir = custom/logs
fit_window_range = 32
fit_window_azimuth = 24
fit_step_range = 16
fit_step_azimuth = 12
height_correlation_threshold = 0.25
fspf_mode = 3
fspf_window_size = 128
fspf_overlap = 8
intensity_background = false""",
            )
            case = load_gamma_atmosphere_config(cfg)[0]
            self.assertEqual(case.output_dir, project / "custom/science")
            self.assertEqual(case.figure_dir, project / "custom/figures")
            self.assertEqual(case.log_dir, project / "custom/logs")
            self.assertEqual(case.fit_window_range, 32)
            self.assertEqual(case.fit_window_azimuth, 24)
            self.assertEqual(case.fit_step_range, 16)
            self.assertEqual(case.fit_step_azimuth, 12)
            self.assertEqual(case.height_correlation_threshold, 0.25)
            self.assertEqual((case.fspf_mode, case.fspf_window_size, case.fspf_overlap), (3, 128, 8))
            self.assertFalse(case.intensity_background)

    def test_polygon_is_required_only_for_polygon_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            with self.assertRaisesRegex(ValueError, "polygon_file is required"):
                load_gamma_atmosphere_config(
                    self._write(
                        root,
                        project,
                        method="gamma_atm_mod_2d_polygon",
                    )
                )
            with self.assertRaisesRegex(ValueError, "polygon_file is only valid"):
                load_gamma_atmosphere_config(
                    self._write(
                        root,
                        project,
                        method="none",
                        extra="polygon_file = config/GAMMA_mb/deformation.poly",
                    )
                )

    def test_strict_values_unknown_keys_and_duplicate_keys_fail(self) -> None:
        invalid = (
            ("fit_window_range = 0", "positive integer"),
            ("fit_step_azimuth = nan", "positive integer"),
            ("height_correlation_threshold = 1.1", "between 0 and 1"),
            ("intensity_background = perhaps", "true or false"),
            ("unexpected = value", "unknown key"),
            ("fspf_window_size = 16", "only valid"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            for extra, message in invalid:
                with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, message):
                    load_gamma_atmosphere_config(
                        self._write(root, project, method="none", extra=extra)
                    )
            cfg = self._write(root, project, method="none")
            cfg.write_text(cfg.read_text() + "method = none\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid GAMMA atmosphere configuration"):
                load_gamma_atmosphere_config(cfg)

    def test_symlinks_and_overlapping_paths_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            manifest = (
                project
                / "S1/ASCENDING_128/GAMMA_mb/DETRENDING/GAMMA_QUAD/"
                "detrending_manifest.json"
            )
            linked = manifest.with_name("linked_manifest.json")
            linked.symlink_to(manifest)
            linked_cfg = self._write(root, project, method="none")
            linked_cfg.write_text(
                linked_cfg.read_text(encoding="utf-8").replace(
                    "DETRENDING/GAMMA_QUAD/detrending_manifest.json",
                    "DETRENDING/GAMMA_QUAD/linked_manifest.json",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "symlink"):
                load_gamma_atmosphere_config(linked_cfg)
            with self.assertRaisesRegex(ValueError, "overlap"):
                load_gamma_atmosphere_config(
                    self._write(
                        root,
                        project,
                        method="none",
                        extra=(
                            "output_dir = "
                            "S1/ASCENDING_128/GAMMA_mb/DETRENDING/GAMMA_QUAD"
                        ),
                    )
                )


if __name__ == "__main__":
    unittest.main()
