"""Execution contracts for NL-InSAR, GAMMA BM3D, and GAMMA ADF."""

from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from geodesy_analysis.insar.filtering.config import load_filtering_config
from geodesy_analysis.insar.filtering.methods.gamma.adf import adf_commands
from geodesy_analysis.insar.filtering.methods.gamma.bm3d import bm3d_commands
from geodesy_analysis.insar.filtering.plan import build_filtering_plan
from geodesy_analysis.insar.filtering.runner import run_filtering


class _FakeGamma:
    def __init__(
        self, fail_on: str | None = None, omit_output_for: str | None = None
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_on = fail_on
        self.omit_output_for = omit_output_for

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append(argv)
        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        Path(stdout_path).write_text("stdout\n", encoding="utf-8")
        Path(stderr_path).write_text("", encoding="utf-8")
        if argv[0] == self.fail_on:
            raise RuntimeError(f"forced {argv[0]} failure")
        if argv[0] == self.omit_output_for:
            return
        if argv[0] == "bm3d":
            np.ones((2, 3), dtype=">c8").tofile(argv[3])
        elif argv[0] == "cc_wave":
            np.full((2, 3), 0.75, dtype=">f4").tofile(argv[4])
        elif argv[0] == "adf":
            np.ones((2, 3), dtype=">c8").tofile(argv[2])
            np.full((2, 3), 0.5, dtype=">f4").tofile(argv[3])
        elif argv[0] in {"rasmph", "rasdt_pwr"}:
            Path(argv[-1]).write_bytes(b"BMquicklook")


class FilteringRunnerTests(unittest.TestCase):
    def _plan(self, root: Path, method: str):
        upstream = root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
        dates = ("20231226", "20240131")
        mli_assets = []
        for date, value in zip(dates, (1.0, 1.5)):
            data = upstream / "MLI" / f"{date}.mli"
            parameter = upstream / "MLI" / f"{date}.mli.par"
            data.parent.mkdir(parents=True, exist_ok=True)
            np.full((2, 3), value, dtype=">f4").tofile(data)
            parameter.write_text("range_samples: 3\nazimuth_lines: 2\n", encoding="utf-8")
            mli_assets.append({"date": date, "data_path": f"MLI/{date}.mli", "parameter_path": f"MLI/{date}.mli.par"})
        pair_name = "20231226-20240131"
        average_mli = upstream / "MLI" / "ave_mli"
        np.full((2, 3), 1.25, dtype=">f4").tofile(average_mli)
        tflt = upstream / "PAIRS" / pair_name / "pair.tflt"
        tflt.parent.mkdir(parents=True)
        np.exp(1j * np.full((2, 3), 0.2)).astype(">c8").tofile(tflt)
        manifest = {
            "schema_version": 2,
            "status": "complete",
            "case_id": "S1/ASCENDING_128",
            "mli_assets": mli_assets,
            "average_mli_path": "MLI/ave_mli",
            "pairs": [{"pair": pair_name, "products": {"differential_interferogram": f"PAIRS/{pair_name}/pair.tflt"}}],
        }
        (upstream / "interferogram_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        config = root / "config/analysis/insar_filtering.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"""[project]\nroot = {root}\n[case:main]\ncase_root = S1/ASCENDING_128\ninterferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json\nmethod = {method}\nsearch_window = 3\nminimum_looks = 1\nfilter_threshold = 0\n""",
            encoding="utf-8",
        )
        (case,) = load_filtering_config(config)
        return build_filtering_plan(case)

    def test_bm3d_uses_legacy_arguments_and_original_tflt_for_coherence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            commands = bm3d_commands(plan.pairs[0], plan, root / "pair")
            self.assertEqual(commands[0][0], "bm3d")
            self.assertEqual(commands[0][1], str(plan.pairs[0].interferogram))
            self.assertEqual(commands[0][2:], ("3", str(root / "pair/pair.tflt.filt"), "1", "6", "10", "-", "8", "16", "3", "0", "-", "-"))
            self.assertEqual(commands[1], ("cc_wave", str(plan.pairs[0].interferogram), str(plan.pairs[0].master_mli), str(plan.pairs[0].slave_mli), str(root / "pair/pair.coh.filt"), "3"))
            fake = _FakeGamma()
            progress: list[str] = []
            summary = run_filtering(plan, command_runner=fake, progress_sink=progress.append)
            self.assertEqual(summary.status, "complete")
            self.assertEqual(
                [call[0] for call in fake.calls],
                ["bm3d", "cc_wave", "rasmph", "rasdt_pwr"],
            )
            self.assertEqual(fake.calls[-2][4:10], ("0", "1", "1", "1", ".35", "rmg.cm"))
            self.assertEqual(fake.calls[-1][2], str(plan.manifest.average_mli))
            self.assertEqual(fake.calls[-1][-2], "cc.cm")
            self._assert_publication(plan, "gamma_bm3d", 0.75)
            self.assertIn('"status":"complete"', progress[-1])

    def test_adf_runs_two_passes_and_does_not_publish_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_adf")
            commands = adf_commands(plan.pairs[0], plan, root / "pair")
            self.assertEqual(commands[0][-3:], ("0.4", "64", "5"))
            self.assertEqual(commands[1][-3:], ("0.4", "16", "5"))
            self.assertEqual(commands[1][1], commands[0][2])
            fake = _FakeGamma()
            run_filtering(plan, command_runner=fake, progress_sink=lambda _: None)
            self.assertEqual(
                [call[0] for call in fake.calls],
                ["adf", "adf", "rasmph", "rasdt_pwr"],
            )
            self._assert_publication(plan, "gamma_adf", 0.5)
            self.assertEqual(list(plan.case.output_dir.rglob("*first-pass*")), [])

    def test_nl_insar_publishes_normalized_products_and_coherent_points(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "nl_insar")
            fake = _FakeGamma()
            summary = run_filtering(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.pair_count, 1)
            self.assertEqual([call[0] for call in fake.calls], ["rasdt_pwr", "rasdt_pwr"])
            self.assertEqual([call[2] for call in fake.calls], ["-", "-"])
            self.assertEqual([call[-2] for call in fake.calls], ["rmg.cm", "cc.cm"])
            self._assert_publication(plan, "nl_insar", None)
            self.assertTrue((plan.case.output_dir / "coherent_points/points.csv").is_file())

    def test_matching_output_skips_but_changed_parameters_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            skipped = run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            self.assertEqual(skipped.status, "skipped")
            config = root / "config/analysis/insar_filtering.cfg"
            config.write_text(config.read_text(encoding="utf-8") + "bm3d_block_size = 12\n", encoding="utf-8")
            changed = build_filtering_plan(load_filtering_config(config)[0])
            with self.assertRaisesRegex(FileExistsError, "different inputs"):
                run_filtering(changed, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            self.assertFalse(plan.case.output_dir.with_name(plan.case.output_dir.name + "-1").exists())

    def test_upstream_quicklook_metadata_does_not_invalidate_scientific_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            source = plan.manifest.source_path
            scientific_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["scientific_manifest_digest"] = scientific_digest
            payload["visualization_dir_project_path"] = (
                "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA"
            )
            source.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            rebuilt = build_filtering_plan(load_filtering_config(root / "config/analysis/insar_filtering.cfg")[0])
            fake = _FakeGamma()
            summary = run_filtering(rebuilt, command_runner=fake, progress_sink=lambda _: None)

            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])

    def test_command_failure_keeps_logs_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            with self.assertRaisesRegex(RuntimeError, "forced"):
                run_filtering(plan, command_runner=_FakeGamma("bm3d"), progress_sink=lambda _: None)
            self.assertFalse(plan.case.output_dir.exists())
            log_parent = root / "S1/ASCENDING_128/LOG/ANALYSIS/FILTERING"
            failed = list(log_parent.glob("GAMMA_BM3D.failed-logs-*"))
            self.assertEqual(len(failed), 1)
            self.assertTrue(list(failed[0].glob("*.stdout.log")))

    def test_missing_quicklook_keeps_logs_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            with self.assertRaisesRegex(RuntimeError, "quicklook is missing"):
                run_filtering(
                    plan,
                    command_runner=_FakeGamma(omit_output_for="rasmph"),
                    progress_sink=lambda _: None,
                )
            self.assertFalse(plan.case.output_dir.exists())
            self.assertFalse(plan.case.visualization_dir.exists())
            failed = list(
                (root / "S1/ASCENDING_128/LOG/ANALYSIS/FILTERING").glob(
                    "GAMMA_BM3D.failed-logs-*"
                )
            )
            self.assertEqual(len(failed), 1)

    def test_legacy_output_repairs_only_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_bm3d")
            run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            manifest_path = plan.case.output_dir / "filtering_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("visualization_dir_project_path")
            for item in manifest["pairs"]:
                item.pop("quicklooks")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance_path = plan.case.output_dir / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("visualization_dir_project_path")
            provenance.pop("quicklook_commands")
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            shutil.rmtree(plan.case.visualization_dir)
            scientific = {
                path: path.read_bytes()
                for path in plan.case.output_dir.rglob("*")
                if path.is_file() and path.name not in {"filtering_manifest.json", "provenance.json"}
            }

            fake = _FakeGamma()
            summary = run_filtering(plan, command_runner=fake, progress_sink=lambda _: None)

            self.assertEqual(summary.status, "repaired")
            self.assertEqual([call[0] for call in fake.calls], ["rasmph", "rasdt_pwr"])
            self.assertEqual({path: path.read_bytes() for path in scientific}, scientific)

    def test_partial_inventory_repairs_but_unrelated_content_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_adf")
            run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            phase = plan.case.visualization_dir / "20231226-20240131.tflt.filt.bmp"
            phase.unlink()
            fake = _FakeGamma()
            summary = run_filtering(plan, command_runner=fake, progress_sink=lambda _: None)
            self.assertEqual(summary.status, "repaired")
            self.assertEqual([call[0] for call in fake.calls], ["rasmph"])

            phase.unlink()
            unrelated = plan.case.visualization_dir / "notes.txt"
            unrelated.write_text("keep\n", encoding="utf-8")
            conflict = _FakeGamma()
            with self.assertRaisesRegex(FileExistsError, "unexpected entry"):
                run_filtering(plan, command_runner=conflict, progress_sink=lambda _: None)
            self.assertEqual(conflict.calls, [])
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep\n")

    def test_expected_quicklook_name_cannot_be_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_adf")
            run_filtering(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            target = plan.case.visualization_dir / "20231226-20240131.tflt.filt.bmp"
            target.unlink()
            outside = root / "outside.bmp"
            outside.write_bytes(b"external")
            target.symlink_to(outside)

            with self.assertRaisesRegex(FileExistsError, "unexpected entry"):
                run_filtering(
                    plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
                )

    def test_science_publication_failure_rolls_back_new_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, "gamma_adf")
            real_replace = __import__("os").replace

            def fail_science_publication(source, destination):
                if Path(destination) == plan.case.output_dir:
                    raise OSError("synthetic science publication failure")
                return real_replace(source, destination)

            with patch(
                "geodesy_analysis.io.os.replace",
                side_effect=fail_science_publication,
            ):
                with self.assertRaisesRegex(OSError, "science publication failure"):
                    run_filtering(
                        plan,
                        command_runner=_FakeGamma(),
                        progress_sink=lambda _: None,
                    )

            self.assertFalse(plan.case.output_dir.exists())
            self.assertFalse(plan.case.visualization_dir.exists())

    def _assert_publication(self, plan, method: str, expected_mean: float | None) -> None:
        output = plan.case.output_dir
        pair = output / "pairs/20231226-20240131"
        self.assertEqual((pair / "pair.tflt.filt").stat().st_size, 48)
        self.assertEqual((pair / "pair.coh.filt").stat().st_size, 24)
        mean = np.fromfile(output / "coh_ave.coh", dtype=">f4")
        self.assertTrue(np.all((mean >= 0) & (mean <= 1)))
        if expected_mean is not None:
            np.testing.assert_allclose(mean, expected_mean)
        manifest = json.loads((output / "filtering_manifest.json").read_text(encoding="utf-8"))
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["method"], method)
        self.assertEqual(manifest["case_id"], "S1/ASCENDING_128")
        self.assertEqual(manifest["pair_count"], 1)
        self.assertEqual(
            manifest["visualization_dir_project_path"],
            f"S1/ASCENDING_128/VISUALIZATION/FILTERING/{plan.case.method.directory_name}",
        )
        self.assertEqual(
            manifest["pairs"][0]["quicklooks"],
            {
                "coherence_project_path": (
                    f"S1/ASCENDING_128/VISUALIZATION/FILTERING/{plan.case.method.directory_name}/"
                    "20231226-20240131.coh.filt.bmp"
                ),
                "phase_project_path": (
                    f"S1/ASCENDING_128/VISUALIZATION/FILTERING/{plan.case.method.directory_name}/"
                    "20231226-20240131.tflt.filt.bmp"
                ),
            },
        )
        self.assertEqual(
            sorted(path.name for path in plan.case.visualization_dir.iterdir()),
            [
                "20231226-20240131.coh.filt.bmp",
                "20231226-20240131.tflt.filt.bmp",
            ],
        )
        self.assertFalse((plan.case.visualization_dir / "pairs").exists())
        self.assertEqual(provenance["input_signature"], manifest["input_signature"])
        self.assertNotIn(str(output.parents[4]), json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
