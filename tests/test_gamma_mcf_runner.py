"""Exact command, publication, and recovery tests for GAMMA MCF."""

from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from geodesy_analysis.insar.unwrapping.gamma.mcf.config import load_gamma_mcf_config
from geodesy_analysis.insar.unwrapping.gamma.mcf.mask import ReferencePoint
from geodesy_analysis.insar.unwrapping.gamma.mcf.plan import build_gamma_mcf_plan
from geodesy_analysis.insar.unwrapping.gamma.mcf.runner import (
    mcf_command,
    run_gamma_mcf,
)
from tests.test_gamma_mcf_plan import GammaMcfPlanTests


class _FakeMcf:
    def __init__(self, fail: bool = False, omit_quicklook: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail
        self.omit_quicklook = omit_quicklook

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append(argv)
        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        Path(stdout_path).write_text("stdout\n", encoding="utf-8")
        Path(stderr_path).write_text("", encoding="utf-8")
        if self.fail and argv[0] == "mcf":
            raise RuntimeError("forced mcf failure")
        if argv[0] == "mcf":
            np.arange(6, dtype=">f4").tofile(argv[4])
        elif argv[0] == "rasdt_pwr" and not self.omit_quicklook:
            Path(argv[-1]).write_bytes(b"BMquicklook")


class GammaMcfRunnerTests(unittest.TestCase):
    def _plan(self, root: Path):
        _, _, config = GammaMcfPlanTests()._project(root)
        return build_gamma_mcf_plan(load_gamma_mcf_config(config)[0])

    def test_mcf_command_preserves_legacy_argument_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            pair = plan.pairs[0]
            reference = ReferencePoint("auto", 2, 1, 0.7, 2, 1)
            command = mcf_command(pair, plan, root / "mask.bmp", reference, root / "out.unw")
            self.assertEqual(
                command,
                (
                    "mcf",
                    str(pair.filtered_interferogram),
                    str(pair.filtered_coherence),
                    str(root / "mask.bmp"),
                    str(root / "out.unw"),
                    "3",
                    "0",
                    "0",
                    "0",
                    "-",
                    "-",
                    "1",
                    "1",
                    "-",
                    "2",
                    "1",
                ),
            )

    def test_publishes_pairs_mask_reference_manifest_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            fake = _FakeMcf()
            progress: list[str] = []
            summary = run_gamma_mcf(plan, command_runner=fake, progress_sink=progress.append)
            self.assertEqual(summary.status, "complete")
            self.assertEqual(
                [call[0] for call in fake.calls],
                ["mcf", "rasdt_pwr", "mcf", "rasdt_pwr"],
            )
            for command in fake.calls[1::2]:
                self.assertEqual(command[2], "-")
                self.assertEqual(command[-2], "rmg.cm")
            output = plan.case.output_dir
            for pair in plan.pairs:
                self.assertEqual((output / "pairs" / pair.name / "pair.tflt.filt.unw").stat().st_size, 24)
            manifest = json.loads((output / "unwrapping_manifest.json").read_text(encoding="utf-8"))
            provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["method"], "gamma_mcf")
            self.assertEqual(manifest["filtering_method"], "nl_insar")
            self.assertEqual(manifest["pair_count"], 2)
            self.assertEqual(
                manifest["visualization_dir_project_path"],
                "S1/ASCENDING_128/VISUALIZATION/UNWRAPPING/GAMMA_MCF",
            )
            self.assertEqual(
                [item["quicklook_project_path"] for item in manifest["pairs"]],
                [
                    "S1/ASCENDING_128/VISUALIZATION/UNWRAPPING/GAMMA_MCF/"
                    f"{pair.name}.tflt.filt.unw.bmp"
                    for pair in plan.pairs
                ],
            )
            self.assertEqual(provenance["reference"]["mode"], "auto")
            self.assertTrue((output / manifest["mask"]["final_mask_path"]).is_file())
            self.assertEqual(
                sorted(path.name for path in plan.case.visualization_dir.iterdir()),
                sorted(f"{pair.name}.tflt.filt.unw.bmp" for pair in plan.pairs),
            )
            self.assertFalse((plan.case.visualization_dir / "mask").exists())
            self.assertEqual(len(list(output.rglob("final.mask.bmp"))), 1)
            self.assertIn('"status":"complete"', progress[-1])

    def test_selected_pair_run_records_scope_and_uses_full_mean_coherence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            selected = plan.pairs[0]
            selected.filtered_coherence.write_bytes(
                np.full((2, 3), 0.1, dtype=">f4").tobytes()
            )
            pair_list = root / "S1/ASCENDING_128/pairs.txt"
            pair_list.write_text(f"{selected.name}\n", encoding="utf-8")
            config = root / "config/analysis/gamma_mcf_unwrapping.cfg"
            plan = build_gamma_mcf_plan(load_gamma_mcf_config(config)[0])
            fake = _FakeMcf()

            summary = run_gamma_mcf(
                plan, command_runner=fake, progress_sink=lambda _: None
            )

            self.assertEqual(summary.pair_count, 1)
            self.assertEqual(
                [call[0] for call in fake.calls], ["mcf", "rasdt_pwr"]
            )
            manifest = json.loads(
                (plan.case.output_dir / "unwrapping_manifest.json").read_text()
            )
            provenance = json.loads(
                (plan.case.output_dir / "provenance.json").read_text()
            )
            self.assertEqual(manifest["pair_count"], 1)
            self.assertEqual(manifest["pair_selection"]["available_pair_count"], 2)
            self.assertEqual(
                manifest["pair_selection"]["selected_pairs"], [selected.name]
            )
            self.assertEqual(
                manifest["pair_selection"]["mode"], "list"
            )
            self.assertEqual(
                manifest["mask_coherence_scope"], "all_filtering_pairs"
            )
            self.assertEqual(
                provenance["pair_selection"]["pair_list_sha256"],
                plan.pair_list_digest,
            )
            self.assertEqual(manifest["pairs"][0]["pair"], selected.name)
            self.assertEqual(manifest["mask"]["valid_count"], 6)

    def test_external_output_paths_are_recorded_as_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            plan = self._plan(root)
            output = Path(external) / "products"
            visualization = Path(external) / "quicklooks"
            external_plan = replace(
                plan,
                case=replace(
                    plan.case,
                    output_dir=output,
                    visualization_dir=visualization,
                ),
            )

            run_gamma_mcf(
                external_plan,
                command_runner=_FakeMcf(),
                progress_sink=lambda _: None,
            )

            manifest = json.loads((output / "unwrapping_manifest.json").read_text())
            self.assertEqual(
                manifest["visualization_dir_project_path"],
                visualization.as_posix(),
            )
            self.assertTrue(
                (visualization / f"{plan.pairs[0].name}.tflt.filt.unw.bmp").is_file()
            )

    def test_complete_result_skips_and_changed_parameters_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            repeated_fake = _FakeMcf()
            repeated = run_gamma_mcf(plan, command_runner=repeated_fake, progress_sink=lambda _: None)
            self.assertEqual(repeated.status, "skipped")
            self.assertEqual(repeated_fake.calls, [])
            changed = replace(plan, case=replace(plan.case, mcf_mode=1))
            changed_fake = _FakeMcf()
            with self.assertRaisesRegex(RuntimeError, "signature changed"):
                run_gamma_mcf(
                    changed, command_runner=changed_fake, progress_sink=lambda _: None
                )
            self.assertEqual(changed_fake.calls, [])

    def test_complete_output_skips_even_when_delegate_would_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            existing = {
                path: path.read_bytes()
                for output in (plan.case.output_dir, plan.case.visualization_dir)
                for path in output.rglob("*")
                if path.is_file()
            }
            fake = _FakeMcf(True)
            summary = run_gamma_mcf(
                plan,
                command_runner=fake,
                progress_sink=lambda _: None,
            )
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])
            self.assertEqual({path: path.read_bytes() for path in existing}, existing)

    def test_missing_quicklook_fails_publication_and_preserves_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            with self.assertRaisesRegex(RuntimeError, "quicklook is missing"):
                run_gamma_mcf(
                    plan,
                    command_runner=_FakeMcf(omit_quicklook=True),
                    progress_sink=lambda _: None,
                )
            self.assertFalse(plan.case.output_dir.exists())
            self.assertFalse(plan.case.visualization_dir.exists())
            failed = list(
                (plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING").glob(
                    "GAMMA_MCF.failed-logs-*"
                )
            )
            self.assertEqual(len(failed), 1)

    def test_missing_figure_directory_repairs_only_quicklooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            manifest_path = plan.case.output_dir / "unwrapping_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("visualization_dir_project_path")
            for item in manifest["pairs"]:
                item.pop("quicklook_project_path")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance_path = plan.case.output_dir / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("visualization_dir_project_path")
            provenance.pop("quicklook_commands")
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            shutil.rmtree(plan.case.visualization_dir)
            fake = _FakeMcf()
            summary = run_gamma_mcf(plan, command_runner=fake, progress_sink=lambda _: None)

            self.assertEqual(summary.status, "figures_repaired")
            self.assertEqual([call[0] for call in fake.calls], ["rasdt_pwr", "rasdt_pwr"])

    def test_figure_repair_preserves_unrelated_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            missing = plan.case.visualization_dir / f"{plan.pairs[0].name}.tflt.filt.unw.bmp"
            missing.unlink()
            fake = _FakeMcf()
            self.assertEqual(
                run_gamma_mcf(plan, command_runner=fake, progress_sink=lambda _: None).status,
                "figures_repaired",
            )
            self.assertEqual([call[0] for call in fake.calls], ["rasdt_pwr"])

            unrelated = plan.case.visualization_dir / "notes.txt"
            unrelated.write_text("keep\n", encoding="utf-8")
            overwrite = _FakeMcf()
            run_gamma_mcf(plan, command_runner=overwrite, progress_sink=lambda _: None)
            self.assertEqual(overwrite.calls, [])
            self.assertTrue(unrelated.exists())

    def test_expected_quicklook_name_cannot_be_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            target = (
                plan.case.visualization_dir
                / f"{plan.pairs[0].name}.tflt.filt.unw.bmp"
            )
            target.unlink()
            outside = root / "outside.bmp"
            outside.write_bytes(b"external")
            target.symlink_to(outside)

            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            self.assertFalse(target.is_symlink())
            self.assertEqual(outside.read_bytes(), b"external")

    def test_complete_output_does_not_enter_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            existing = {
                path: path.read_bytes()
                for output in (plan.case.output_dir, plan.case.visualization_dir)
                for path in output.rglob("*")
                if path.is_file()
            }
            real_replace = __import__("os").replace

            def fail_science_publication(source, destination):
                if Path(destination) == plan.case.output_dir and Path(source).name != "previous":
                    raise OSError("synthetic science publication failure")
                return real_replace(source, destination)

            with patch(
                "geodesy_analysis.io.os.replace",
                side_effect=fail_science_publication,
            ):
                summary = run_gamma_mcf(
                    plan,
                    command_runner=_FakeMcf(),
                    progress_sink=lambda _: None,
                )
            self.assertEqual(summary.status, "skipped")

            self.assertEqual({path: path.read_bytes() for path in existing}, existing)

    def test_filter_quicklook_metadata_does_not_prevent_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            source = plan.filtering.source_path
            scientific_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["scientific_manifest_digest"] = scientific_digest
            payload["visualization_dir_project_path"] = (
                "S1/ASCENDING_128/VISUALIZATION/FILTERING/NL_INSAR"
            )
            source.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            rebuilt = self._plan_from_config(root)
            fake = _FakeMcf()
            summary = run_gamma_mcf(rebuilt, command_runner=fake, progress_sink=lambda _: None)

            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])

    def _plan_from_config(self, root: Path):
        config = root / "config/analysis/gamma_mcf_unwrapping.cfg"
        return build_gamma_mcf_plan(load_gamma_mcf_config(config)[0])


if __name__ == "__main__":
    unittest.main()
