"""Strict configuration tests for the common filtering workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.filtering.config import load_filtering_config
from geodesy_analysis.insar.filtering.models import FilteringMethod


class FilteringConfigTests(unittest.TestCase):
    def _manifest(self, root: Path, relative: str = "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path

    def _write(self, root: Path, body: str) -> Path:
        path = root / "config/analysis/insar_filtering.cfg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def _body(self, root: Path, extra: str = "") -> str:
        return f"""
[project]
root = {root}

[case:main]
case_root = S1/ASCENDING_128
interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json
method = nl_insar
{extra}
"""

    def test_loads_all_methods_and_derives_distinct_default_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._manifest(root)
            config = self._write(
                root,
                f"""
[project]
root = {root}
[defaults]
search_window = 15
filter_threshold = 0.4
[case:nl]
case_root = S1/ASCENDING_128
interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json
method = nl_insar
[case:bm3d]
case_root = S1/ASCENDING_128
interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json
method = GAMMA_BM3D
[case:adf]
case_root = S1/ASCENDING_128
interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json
method = gamma_adf
""",
            )
            nl, bm3d, adf = load_filtering_config(config)
            self.assertEqual(
                [case.method for case in (nl, bm3d, adf)],
                [FilteringMethod.NL_INSAR, FilteringMethod.GAMMA_BM3D, FilteringMethod.GAMMA_ADF],
            )
            self.assertEqual(nl.search_window, 15)
            self.assertEqual(nl.filter_threshold, 0.4)
            self.assertEqual(nl.patch_size, 3)
            self.assertEqual(nl.minimum_looks, 80)
            self.assertEqual(nl.coherence_window, 11)
            self.assertEqual(nl.tile_size, 96)
            self.assertEqual(nl.point_threshold, 0.3)
            self.assertEqual(bm3d.bm3d_block_size, 8)
            self.assertEqual((adf.adf_first_window, adf.adf_second_window), (64, 16))
            self.assertEqual(
                [case.output_dir for case in (nl, bm3d, adf)],
                [
                    root / "S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR",
                    root / "S1/ASCENDING_128/ANALYSIS/FILTERING/GAMMA_BM3D",
                    root / "S1/ASCENDING_128/ANALYSIS/FILTERING/GAMMA_ADF",
                ],
            )
            self.assertEqual(
                [case.visualization_dir for case in (nl, bm3d, adf)],
                [
                    root / "S1/ASCENDING_128/VISUALIZATION/FILTERING/NL_INSAR",
                    root / "S1/ASCENDING_128/VISUALIZATION/FILTERING/GAMMA_BM3D",
                    root / "S1/ASCENDING_128/VISUALIZATION/FILTERING/GAMMA_ADF",
                ],
            )

    def test_explicit_project_confined_output_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._manifest(root)
            (case,) = load_filtering_config(
                self._write(root, self._body(root, "output_dir = results/manual_nl"))
            )
            self.assertEqual(case.output_dir, (root / "results/manual_nl").resolve())

    def test_explicit_absolute_outputs_may_be_outside_project_and_remain_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            self._manifest(root)
            output = Path(external) / "science"
            visualization = Path(external) / "quicklooks"
            (case,) = load_filtering_config(
                self._write(
                    root,
                    self._body(
                        root,
                        f"output_dir = {output}\nvisualization_dir = {visualization}",
                    )
                )
            )
            self.assertEqual(
                case.output_dir,
                output.resolve(),
            )
            self.assertEqual(case.visualization_dir, visualization.resolve())

            with self.assertRaisesRegex(ValueError, "must not overlap"):
                load_filtering_config(
                    self._write(
                        root,
                        self._body(root, f"output_dir = {output}\nvisualization_dir = {output}"),
                    )
                )
            with self.assertRaisesRegex(ValueError, "log directory"):
                load_filtering_config(
                    self._write(
                        root,
                        self._body(
                            root,
                            "output_dir = S1/ASCENDING_128/LOG/ANALYSIS/FILTERING/NL_INSAR",
                        ),
                    )
                )

    def test_selected_case_does_not_validate_other_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._manifest(root)
            config = self._write(
                root,
                self._body(root)
                + """
[case:unselected]
method = unsupported
""",
            )
            (case,) = load_filtering_config(config, case_name="main")
            self.assertEqual(case.name, "main")
            with self.assertRaisesRegex(ValueError, "unknown case"):
                load_filtering_config(config, case_name="missing")

    def test_requires_explicit_output_when_manifest_has_no_analysis_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._manifest(root, "S1/ASCENDING_128/import/interferogram_manifest.json")
            body = self._body(root).replace(
                "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json",
                "S1/ASCENDING_128/import/interferogram_manifest.json",
            )
            with self.assertRaisesRegex(ValueError, "output_dir.*required"):
                load_filtering_config(self._write(root, body))

    def test_accepts_external_interferogram_manifest_with_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            manifest = self._manifest(Path(external), "results/interferogram_manifest.json")
            body = self._body(root).replace(
                "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json",
                str(manifest),
            )
            (case,) = load_filtering_config(
                self._write(root, body + "output_dir = ANALYSIS/FILTERING/custom\n")
            )
            self.assertEqual(case.interferogram_manifest, manifest.resolve())

    def test_rejects_unknown_missing_and_unsafe_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            self._manifest(root)
            cases = (
                ("method = nl_insar", "method = other", "method must be"),
                ("method = nl_insar", "method = nl_insar\nsurprise = yes", "unknown key"),
                ("method = nl_insar", "", "missing keys.*method"),
                (
                    "interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json",
                    "interferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/missing.json",
                    "does not exist",
                ),
            )
            for old, new, message in cases:
                with self.subTest(new=new):
                    with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                        load_filtering_config(self._write(root, self._body(root).replace(old, new)))

            external_output = Path(outside) / "external-output"
            (case,) = load_filtering_config(
                self._write(
                    root,
                    self._body(root, f"output_dir = {external_output}"),
                )
            )
            self.assertEqual(case.output_dir, external_output.resolve())


if __name__ == "__main__":
    unittest.main()
