"""Exact command, publication, and recovery tests for GAMMA MCF."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append(argv)
        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        Path(stdout_path).write_text("stdout\n", encoding="utf-8")
        Path(stderr_path).write_text("", encoding="utf-8")
        if self.fail:
            raise RuntimeError("forced mcf failure")
        np.arange(6, dtype=">f4").tofile(argv[4])


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
            self.assertEqual(len(fake.calls), 2)
            output = plan.case.output_dir
            for pair in plan.pairs:
                self.assertEqual((output / "pairs" / pair.name / "pair.tflt.filt.unw").stat().st_size, 24)
            manifest = json.loads((output / "unwrapping_manifest.json").read_text(encoding="utf-8"))
            provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["method"], "gamma_mcf")
            self.assertEqual(manifest["filtering_method"], "nl_insar")
            self.assertEqual(manifest["pair_count"], 2)
            self.assertEqual(provenance["reference"]["mode"], "auto")
            self.assertTrue((output / manifest["mask"]["final_mask_path"]).is_file())
            self.assertIn('"status":"complete"', progress[-1])

    def test_matching_output_skips_changed_input_conflicts_and_failure_keeps_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None)
            self.assertEqual(run_gamma_mcf(plan, command_runner=_FakeMcf(), progress_sink=lambda _: None).status, "skipped")
            changed = replace(plan, case=replace(plan.case, mcf_mode=1))
            with self.assertRaisesRegex(FileExistsError, "different inputs"):
                run_gamma_mcf(changed, command_runner=_FakeMcf(), progress_sink=lambda _: None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            with self.assertRaisesRegex(RuntimeError, "forced"):
                run_gamma_mcf(plan, command_runner=_FakeMcf(True), progress_sink=lambda _: None)
            self.assertFalse(plan.case.output_dir.exists())
            failed = list((plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING").glob("GAMMA_MCF.failed-logs-*"))
            self.assertEqual(len(failed), 1)
            self.assertTrue(list(failed[0].glob("*.stdout.log")))


if __name__ == "__main__":
    unittest.main()
