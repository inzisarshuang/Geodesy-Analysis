"""Tests for transactional GAMMA baseline execution and publication."""

from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.insar.baseline_selection.gamma.models import GammaBaselineCase
from geodesy_analysis.insar.baseline_selection.gamma.plan import build_gamma_baseline_plan
from geodesy_analysis.insar.baseline_selection.gamma.publication import parse_berp_sc
from geodesy_analysis.insar.baseline_selection.gamma.runner import run_gamma_baseline


class _FakeBaseCalc:
    def __init__(self, *, create_outputs: bool = True) -> None:
        self.create_outputs = create_outputs
        self.calls: list[tuple[str, ...]] = []

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        normalized = tuple(command)
        self.calls.append(normalized)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("base_calc complete\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if self.create_outputs:
            (cwd / "Berp_SC").write_text(
                "1 20231226 20231214 10 -12\n"
                "2 20231214 20231226 -10 12\n"
                "3 20231226 20231226 0 0\n"
                "4 20231226 20240107 4 12\n",
                encoding="utf-8",
            )
            (cwd / "itab_SC").write_text("1 2\n", encoding="utf-8")
        return None


class GammaBaselineRunnerTests(unittest.TestCase):
    """Pin pair normalization, scientific publication, and restart safety."""

    def _plan(self, root: Path):
        stack = root / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET"
        data = stack / "RSLC"
        data.mkdir(parents=True, exist_ok=True)
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
                    "data_path": f"RSLC/{date}.rslc",
                    "parameter_path": f"RSLC/{date}.rslc.par",
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        case = GammaBaselineCase(
            paths=bind_analysis_case(root, "ascending", "S1/ASCENDING_128"),
            registered_stack=manifest,
            polarization="VV",
            network_type="SBAS",
            max_perpendicular_baseline=300.0,
            max_temporal_baseline=100.0,
            output_dir=root / "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA",
        )
        return build_gamma_baseline_plan(case)

    def test_parse_berp_removes_self_pairs_normalizes_and_sorts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Berp_SC"
            source.write_text(
                "1 20231226 20231214 10 -12\n"
                "2 20231226 20231226 0 0\n"
                "3 20231226 20240107 4 12\n",
                encoding="utf-8",
            )
            records = parse_berp_sc(source)
            self.assertEqual(
                [(row.master, row.slave, row.perpendicular, row.temporal) for row in records],
                [
                    ("20231214", "20231226", -10.0, 12.0),
                    ("20231226", "20240107", 4.0, 12.0),
                ],
            )

    def test_publishes_inventory_network_manifest_and_two_stage_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            fake = _FakeBaseCalc()
            progress: list[str] = []
            summary = run_gamma_baseline(
                plan,
                command_runner=fake,
                progress_sink=progress.append,
            )
            output = plan.case.output_dir
            self.assertEqual(summary.status, "complete")
            self.assertEqual(summary.pair_count, 2)
            self.assertEqual((output / "images").read_text(encoding="utf-8"), plan.images_text)
            self.assertEqual(
                (output / "image_pairs_SBAS").read_text(encoding="utf-8"),
                "20231214-20231226\n20231226-20240107\n",
            )
            self.assertEqual(
                (output / "baseline_select_SBAS").read_text(encoding="utf-8"),
                "20231214 20231226 -10 12\n20231226 20240107 4 12\n",
            )
            manifest = json.loads(
                (output / "baseline_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["case_id"], "S1/ASCENDING_128")
            self.assertEqual(manifest["backend"], {"name": "gamma"})
            self.assertEqual(
                manifest["registered_stack_project_path"],
                "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            )
            self.assertEqual(manifest["stack_digest"], plan.stack.source_digest)
            self.assertEqual(manifest["reference_date"], "20231226")
            self.assertEqual(manifest["polarization"], "VV")
            self.assertEqual(manifest["network_type"], "SBAS")
            self.assertEqual(manifest["network_path"], "baseline_select_SBAS")
            self.assertEqual(manifest["pair_count"], 2)
            self.assertNotIn("plot_path", manifest)
            self.assertNotIn("warnings", manifest)
            self.assertEqual(list(output.glob("*.png")), [])
            provenance = json.loads(
                (output / "provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["schema_version"], 2)
            self.assertEqual(provenance["case_id"], "S1/ASCENDING_128")
            self.assertEqual(provenance["backend"], {"name": "gamma"})
            self.assertEqual(
                provenance["registered_stack_project_path"],
                "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            )
            self.assertNotIn(str(root), json.dumps(manifest, sort_keys=True))
            self.assertNotIn(str(root), json.dumps(provenance, sort_keys=True))
            self.assertEqual(len(fake.calls), 1)
            events = [json.loads(line.split(" ", 1)[1]) for line in progress]
            self.assertEqual([event["total"] for event in events], [2, 2, 2, 2])
            self.assertEqual(
                [(event["event"], event["stage"]) for event in events],
                [
                    ("batch_started", "prepare"),
                    ("item_started", "base_calc"),
                    ("item_finished", "base_calc"),
                    ("batch_finished", "publish"),
                ],
            )
            log = (
                root
                / "S1/ASCENDING_128/LOG/ANALYSIS/BASELINE_SELECTION/GAMMA/base_calc.stdout.log"
            )
            self.assertTrue(log.is_file())

    def test_runner_has_no_plot_callback(self) -> None:
        self.assertNotIn("plotter", inspect.signature(run_gamma_baseline).parameters)

    def test_missing_gamma_output_fails_without_publishing_and_keeps_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            with self.assertRaisesRegex(ValueError, "base_calc did not create"):
                run_gamma_baseline(
                    plan,
                    command_runner=_FakeBaseCalc(create_outputs=False),
                )
            self.assertFalse(plan.case.output_dir.exists())
            failures = list(
                (root / "S1/ASCENDING_128/LOG/ANALYSIS/BASELINE_SELECTION").glob(
                    "GAMMA.failed-logs-*"
                )
            )
            self.assertEqual(len(failures), 1)
            self.assertTrue((failures[0] / "base_calc.stdout.log").is_file())

    def test_invalid_complete_manifest_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_baseline(plan, command_runner=_FakeBaseCalc())
            manifest_path = plan.case.output_dir / "baseline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pair_count"] = 99
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            fake = _FakeBaseCalc()
            with self.assertRaisesRegex(RuntimeError, "pair_count"):
                run_gamma_baseline(plan, command_runner=fake)
            self.assertEqual(fake.calls, [])
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["pair_count"],
                99,
            )

    def test_existing_output_is_skipped_and_changed_stack_requires_new_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            first = _FakeBaseCalc()
            first_summary = run_gamma_baseline(plan, command_runner=first)
            self.assertEqual(first_summary.status, "complete")
            self.assertEqual(len(first.calls), 1)

            second = _FakeBaseCalc()
            summary = run_gamma_baseline(plan, command_runner=second)
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(second.calls, [])

            payload = json.loads(plan.case.registered_stack.read_text(encoding="utf-8"))
            payload["track"] = "128"
            plan.case.registered_stack.write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
            changed = build_gamma_baseline_plan(plan.case)
            changed_runner = _FakeBaseCalc()
            with self.assertRaisesRegex(RuntimeError, "signature changed"):
                run_gamma_baseline(changed, command_runner=changed_runner)
            self.assertEqual(changed_runner.calls, [])

    def test_complete_output_skips_even_when_runner_would_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_baseline(plan, command_runner=_FakeBaseCalc())
            output = plan.case.output_dir
            original_manifest = (output / "baseline_manifest.json").read_bytes()
            fake = _FakeBaseCalc(create_outputs=False)
            summary = run_gamma_baseline(plan, command_runner=fake)
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])
            self.assertEqual(
                (output / "baseline_manifest.json").read_bytes(), original_manifest
            )
            self.assertFalse((output / "partial").exists())

    def test_existing_output_with_changed_identity_is_rejected(self) -> None:
        mutations = (
            ("case_id", "S1/DESCENDING_135"),
            (
                "registered_stack_project_path",
                "S1/DESCENDING_135/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            ),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self._plan(root)
                run_gamma_baseline(plan, command_runner=_FakeBaseCalc())
                manifest_path = plan.case.output_dir / "baseline_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[key] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, "identity is inconsistent"):
                    run_gamma_baseline(plan, command_runner=_FakeBaseCalc())

    def test_legacy_schema_one_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_baseline(plan, command_runner=_FakeBaseCalc())
            manifest_path = plan.case.output_dir / "baseline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            manifest.pop("backend")
            manifest.pop("case_id")
            manifest.pop("registered_stack_project_path")
            manifest["plot_path"] = "missing-legacy-plot.png"
            manifest["warnings"] = ["legacy plot warning"]
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True), encoding="utf-8"
            )
            provenance_path = plan.case.output_dir / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("backend")
            provenance.pop("case_id")
            provenance.pop("registered_stack_project_path")
            provenance.pop("schema_version")
            provenance_path.write_text(
                json.dumps(provenance, sort_keys=True), encoding="utf-8"
            )
            fake = _FakeBaseCalc()
            progress: list[str] = []
            with self.assertRaisesRegex(RuntimeError, "schema is not version 2"):
                run_gamma_baseline(
                    plan, command_runner=fake, progress_sink=progress.append
                )
            self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
