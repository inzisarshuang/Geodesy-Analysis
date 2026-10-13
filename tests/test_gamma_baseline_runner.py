"""Tests for transactional GAMMA baseline execution and publication."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
    """Pin pair normalization, publication, restart safety, and plot warnings."""

    def _plan(self, root: Path):
        stack = root / "PRE" / "RSLC"
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
            name="ascending",
            project_root=root,
            registered_stack=manifest,
            polarization="VV",
            network_type="SBAS",
            max_perpendicular_baseline=300.0,
            max_temporal_baseline=100.0,
            output_dir=root / "ANALYSIS/GAMMA/ascending/BASELINE",
        )
        return build_gamma_baseline_plan(case)

    @staticmethod
    def _plotter(**kwargs):
        Path(kwargs["out_file"]).write_bytes(b"png")
        return str(kwargs["out_file"])

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

    def test_publishes_inventory_network_manifest_progress_and_plot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            fake = _FakeBaseCalc()
            progress: list[str] = []
            summary = run_gamma_baseline(
                plan,
                command_runner=fake,
                progress_sink=progress.append,
                plotter=self._plotter,
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
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["stack_digest"], plan.stack.source_digest)
            self.assertEqual(manifest["reference_date"], "20231226")
            self.assertEqual(manifest["polarization"], "VV")
            self.assertEqual(manifest["network_type"], "SBAS")
            self.assertEqual(manifest["network_path"], "baseline_select_SBAS")
            self.assertEqual(manifest["pair_count"], 2)
            self.assertTrue((output / manifest["plot_path"]).is_file())
            self.assertEqual(len(fake.calls), 1)
            self.assertIn('"event":"batch_started"', progress[0])
            self.assertIn('"status":"complete"', progress[-1])
            log = root / "LOG/ANALYSIS/GAMMA/BASELINE/ascending/base_calc.stdout.log"
            self.assertTrue(log.is_file())

    def test_missing_gamma_output_fails_without_publishing_and_keeps_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            with self.assertRaisesRegex(ValueError, "base_calc did not create"):
                run_gamma_baseline(
                    plan,
                    command_runner=_FakeBaseCalc(create_outputs=False),
                    plotter=self._plotter,
                )
            self.assertFalse(plan.case.output_dir.exists())
            failures = list(
                (root / "LOG/ANALYSIS/GAMMA/BASELINE").glob(
                    "ascending.failed-logs-*"
                )
            )
            self.assertEqual(len(failures), 1)
            self.assertTrue((failures[0] / "base_calc.stdout.log").is_file())

    def test_existing_manifest_pair_count_must_match_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_baseline(
                plan, command_runner=_FakeBaseCalc(), plotter=self._plotter
            )
            manifest_path = plan.case.output_dir / "baseline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pair_count"] = 99
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "incomplete or invalid"):
                run_gamma_baseline(
                    plan,
                    command_runner=_FakeBaseCalc(),
                    plotter=self._plotter,
                )

    def test_matching_output_skips_but_changed_stack_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            first = _FakeBaseCalc()
            run_gamma_baseline(plan, command_runner=first, plotter=self._plotter)
            second = _FakeBaseCalc()
            summary = run_gamma_baseline(plan, command_runner=second, plotter=self._plotter)
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(second.calls, [])

            payload = json.loads(plan.case.registered_stack.read_text(encoding="utf-8"))
            payload["track"] = "128"
            plan.case.registered_stack.write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
            changed = build_gamma_baseline_plan(plan.case)
            with self.assertRaisesRegex(FileExistsError, "different inputs"):
                run_gamma_baseline(
                    changed,
                    command_runner=_FakeBaseCalc(),
                    plotter=self._plotter,
                )

    def test_plot_failure_is_warning_and_network_still_publishes(self) -> None:
        def broken_plotter(**kwargs):
            raise RuntimeError("font unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            summary = run_gamma_baseline(
                plan,
                command_runner=_FakeBaseCalc(),
                plotter=broken_plotter,
            )
            self.assertEqual(summary.status, "complete")
            self.assertEqual(len(summary.warnings), 1)
            manifest = json.loads(
                (plan.case.output_dir / "baseline_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIsNone(manifest["plot_path"])
            self.assertTrue((plan.case.output_dir / "baseline_select_SBAS").is_file())


if __name__ == "__main__":
    unittest.main()
