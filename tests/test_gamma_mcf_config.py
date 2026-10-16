"""Strict configuration tests for GAMMA MCF unwrapping."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.unwrapping.gamma.mcf.config import load_gamma_mcf_config


class GammaMcfConfigTests(unittest.TestCase):
    def _files(self, root: Path, *, under_analysis: bool = True) -> tuple[Path, Path]:
        relative = (
            "S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR/filtering_manifest.json"
            if under_analysis
            else "S1/ASCENDING_128/import/filtering_manifest.json"
        )
        manifest = root / relative
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        external = root / "S1/ASCENDING_128/config/analysis/external_mask.bmp"
        external.parent.mkdir(parents=True)
        external.write_bytes(b"mask")
        return manifest, external

    def _write(self, root: Path, body: str) -> Path:
        path = root / "config/analysis/gamma_mcf_unwrapping.cfg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def _body(self, root: Path, extra: str = "", manifest: str = "S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR/filtering_manifest.json") -> str:
        return f"""[project]\nroot = {root}\n[case:main]\ncase_root = S1/ASCENDING_128\nfiltering_manifest = {manifest}\nmcf_mode = 0\n{extra}\n"""

    def test_defaults_and_automatic_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._files(root)
            (case,) = load_gamma_mcf_config(self._write(root, self._body(root)))
            self.assertEqual(case.mcf_mode, 0)
            self.assertEqual(case.reference_mode, "auto")
            self.assertEqual(case.coherence_threshold, 0.3)
            self.assertIsNone(case.external_mask)
            self.assertEqual(case.mask_operation, "and")
            self.assertEqual(case.output_dir, root / "S1/ASCENDING_128/ANALYSIS/UNWRAPPING/GAMMA_MCF")

    def test_manual_reference_external_mask_and_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, external = self._files(root)
            (case,) = load_gamma_mcf_config(
                self._write(
                    root,
                    self._body(
                        root,
                        f"reference_mode = manual\nreference_range = 4\nreference_azimuth = 7\nexternal_mask = {external}\nmask_operation = or\noutput_dir = custom/unwrapped",
                    ),
                )
            )
            self.assertEqual((case.reference_range, case.reference_azimuth), (4, 7))
            self.assertEqual(case.external_mask, external)
            self.assertEqual(case.mask_operation, "or")
            self.assertEqual(case.output_dir, root / "custom/unwrapped")

    def test_requires_explicit_output_without_analysis_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._files(root, under_analysis=False)
            with self.assertRaisesRegex(ValueError, "output_dir.*required"):
                load_gamma_mcf_config(
                    self._write(
                        root,
                        self._body(root, manifest="S1/ASCENDING_128/import/filtering_manifest.json"),
                    )
                )

    def test_rejects_invalid_modes_reference_keys_and_boundaries(self) -> None:
        replacements = (
            ("mcf_mode = 0", "mcf_mode = 4", "0 through 3"),
            ("mcf_mode = 0", "mcf_mode = 0\nreference_mode = manual", "reference_range.*reference_azimuth"),
            ("mcf_mode = 0", "mcf_mode = 0\nreference_mode = other", "auto or manual"),
            ("mcf_mode = 0", "mcf_mode = 0\ncoherence_threshold = 2", "between 0 and 1"),
            ("mcf_mode = 0", "mcf_mode = 0\nunknown = yes", "unknown key"),
        )
        for old, new, message in replacements:
            with self.subTest(new=new), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._files(root)
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_mcf_config(self._write(root, self._body(root).replace(old, new)))
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            self._files(root)
            with self.assertRaisesRegex(ValueError, "project root"):
                load_gamma_mcf_config(self._write(root, self._body(root, f"output_dir = {outside}")))


if __name__ == "__main__":
    unittest.main()
