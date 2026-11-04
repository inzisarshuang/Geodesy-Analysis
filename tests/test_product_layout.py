"""Tests for method-centric Analysis product and figure roots."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.common.product_layout import AnalysisProductLayout


class ProductLayoutTests(unittest.TestCase):
    def test_s1_and_saocom_defaults_use_declared_method_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for project, processing in (
                ("S1/ASCENDING_128", "S1/ASCENDING_128/GAMMA"),
                ("SAOCOM/GUIZHOU", "SAOCOM/GUIZHOU/GAMMA_mb"),
            ):
                with self.subTest(processing=processing):
                    paths = bind_analysis_case(root, "main", project, processing)
                    layout = AnalysisProductLayout(paths)
                    method = root / processing
                    self.assertEqual(layout.product("INTF", "PAIRS"), method / "INTF/PAIRS")
                    self.assertEqual(layout.figures("INTF"), method / "FIGURES/INTF")
                    self.assertEqual(layout.logs("FILTERING"), method / "LOG/ANALYSIS/FILTERING")

    def test_processing_root_must_be_one_method_below_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ("S1/OTHER/GAMMA", "S1/ASCENDING_128", "S1/ASCENDING_128/A/B"):
                with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "processing_root"
                ):
                    bind_analysis_case(root, "main", "S1/ASCENDING_128", value)

    def test_science_figures_logs_and_inputs_must_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = bind_analysis_case(
                root, "main", "S1/ASCENDING_128", "S1/ASCENDING_128/GAMMA"
            )
            layout = AnalysisProductLayout(paths)
            with self.assertRaisesRegex(ValueError, "overlap"):
                layout.require_disjoint(
                    science=layout.product("INTF"),
                    figures=layout.product("INTF", "FIGURES"),
                    logs=layout.logs("INTF"),
                    inputs=(),
                )

    def test_portable_serialization_prefers_project_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = bind_analysis_case(
                root, "main", "S1/ASCENDING_128", "S1/ASCENDING_128/GAMMA"
            )
            layout = AnalysisProductLayout(paths)
            self.assertEqual(
                layout.serialize(layout.product("BASELINE")),
                "S1/ASCENDING_128/GAMMA/BASELINE",
            )
            self.assertEqual(layout.serialize(Path("/external/result")), "/external/result")


if __name__ == "__main__":
    unittest.main()
