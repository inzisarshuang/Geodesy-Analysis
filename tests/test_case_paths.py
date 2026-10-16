"""Tests for the Analysis project/case path boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    AnalysisCasePaths,
    bind_analysis_case,
    resolve_case_input,
    resolve_case_output,
    resolve_project_input,
)


class AnalysisCasePathTests(unittest.TestCase):
    """Pin formal case identity and symlink-safe containment."""

    def test_binding_resolves_existing_project_without_creating_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "study"
            project.mkdir()

            paths = bind_analysis_case(project, "main", "S1/ASCENDING_128")

            self.assertEqual(
                paths,
                AnalysisCasePaths(
                    label="main",
                    case_id="S1/ASCENDING_128",
                    project_root=project.resolve(),
                    case_root=(project / "S1" / "ASCENDING_128").resolve(),
                ),
            )
            self.assertFalse(paths.case_root.exists())

    def test_binding_rejects_malformed_case_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            invalid = (
                "",
                "/S1/ASCENDING_128",
                "ASCENDING_128",
                "S1/ASCENDING/128",
                "s1/ASCENDING_128",
                "S1/ascending_128",
                r"S1\ASCENDING_128",
                "S1/./ASCENDING_128",
                "S1/../ASCENDING_128",
                "S1//ASCENDING_128",
                "~/ASCENDING_128",
            )
            for value in invalid:
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        bind_analysis_case(project, "main", value)

    def test_binding_rejects_case_root_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "study"
            outside = root / "outside"
            project.mkdir()
            outside.mkdir()
            (project / "S1").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "case root.*project root"):
                bind_analysis_case(project, "main", "S1/ASCENDING_128")

    def test_project_and_case_inputs_apply_distinct_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "study"
            project.mkdir()
            shared = project / "TOPOGRAPHY" / "catalog.json"
            shared.parent.mkdir()
            shared.write_text("{}\n", encoding="utf-8")
            own = project / "S1" / "ASCENDING_128" / "PRE" / "input.json"
            own.parent.mkdir(parents=True)
            own.write_text("{}\n", encoding="utf-8")
            other = project / "S1" / "DESCENDING_135" / "PRE" / "input.json"
            other.parent.mkdir(parents=True)
            other.write_text("{}\n", encoding="utf-8")
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            paths = bind_analysis_case(project, "main", "S1/ASCENDING_128")

            self.assertEqual(
                resolve_project_input(paths, "TOPOGRAPHY/catalog.json"),
                shared.resolve(),
            )
            self.assertEqual(
                resolve_case_input(paths, "S1/ASCENDING_128/PRE/input.json"),
                own.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "project input.*project root"):
                resolve_project_input(paths, outside)
            with self.assertRaisesRegex(ValueError, "case input.*case root"):
                resolve_case_input(paths, "S1/DESCENDING_135/PRE/input.json")
            with self.assertRaises(FileNotFoundError):
                resolve_project_input(paths, "TOPOGRAPHY/missing.json")

    def test_case_output_allows_future_path_but_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "study"
            case = project / "S1" / "ASCENDING_128"
            outside = root / "outside"
            case.mkdir(parents=True)
            outside.mkdir()
            paths = bind_analysis_case(project, "main", "S1/ASCENDING_128")

            output = resolve_case_output(
                paths, "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA"
            )
            self.assertEqual(
                output, case / "ANALYSIS" / "BASELINE_SELECTION" / "GAMMA"
            )
            self.assertFalse(output.exists())

            (case / "ANALYSIS").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "case output.*case root"):
                resolve_case_output(
                    paths, "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA"
                )


if __name__ == "__main__":
    unittest.main()
