"""Semantic and transactional tests for single-pair GAMMA DInSAR."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.time_series.gamma.dinsar.config import (
    load_gamma_dinsar_config,
)
from geodesy_analysis.insar.time_series.gamma.dinsar.plan import (
    build_gamma_dinsar_plan,
)
from geodesy_analysis.insar.time_series.gamma.dinsar.runner import run_gamma_dinsar
from geodesy_analysis.insar.time_series.gamma.dinsar.publication import (
    gamma_dinsar_input_signature,
)

import test_gamma_time_series_common as common_fixture


class _FakeGamma:
    def __init__(self, *, fail_program: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_program = fail_program

    @staticmethod
    def _float(path: str, count: int) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.arange(1, count + 1, dtype=">f4").tofile(target)

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append(argv)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("complete\n")
        stderr_path.write_text("")
        if argv[0] == self.fail_program:
            raise RuntimeError(f"synthetic {argv[0]} failure")
        if argv[0] == "dispmap":
            self._float(argv[5], 4)
        elif argv[0] == "geocode_back":
            self._float(argv[4], 6)
        elif argv[0] == "rasdt_pwr":
            Path(argv[-1]).write_bytes(b"quicklook")
        return None


class GammaDinsarTests(unittest.TestCase):
    def _config(self, root: Path, *, pair: str | None = None, extra: str = ""):
        fixture = common_fixture.GammaTimeSeriesCommonTests()._fixture(root)
        pair_line = "" if pair is None else f"pair = {pair}\n"
        cfg = root / "dinsar.cfg"
        cfg.write_text(
            f"""[project]
root = {fixture['project']}

[case:ascending]
project = S1/ASCENDING_128
processing_root = S1/ASCENDING_128/GAMMA_mb
atmosphere_manifest = {fixture['atmosphere'].relative_to(fixture['project'])}
{pair_line}{extra}
""",
            encoding="utf-8",
        )
        return fixture, cfg

    def test_config_requires_exactly_one_pair_and_derives_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, cfg = self._config(root, pair=common_fixture.GammaTimeSeriesCommonTests.pairs[0])
            case = load_gamma_dinsar_config(cfg)[0]
            processing = fixture["project"] / "S1/ASCENDING_128/GAMMA_mb"
            self.assertEqual(case.output_dir, processing / "TIMESERIES/DINSAR")
            self.assertEqual(case.figure_dir, processing / "FIGURES/TIMESERIES/DINSAR")
            self.assertEqual(case.log_dir, processing / "LOG/ANALYSIS/TIMESERIES/DINSAR")
        for pair, message in ((None, "missing"), ("20231027-20231226,20231226-20240107", "pair")):
            with self.subTest(pair=pair), tempfile.TemporaryDirectory() as directory:
                _, cfg = self._config(Path(directory), pair=pair)
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_dinsar_config(cfg)

    def test_unknown_pair_fails_before_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = self._config(Path(directory), pair="20231027-20240107")
            with self.assertRaisesRegex(ValueError, "selected pair"):
                build_gamma_dinsar_plan(load_gamma_dinsar_config(cfg)[0])

    def test_signature_covers_geocoding_assets_and_command_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pair = common_fixture.GammaTimeSeriesCommonTests.pairs[0]
            _, cfg = self._config(Path(directory), pair=pair)
            plan = build_gamma_dinsar_plan(load_gamma_dinsar_config(cfg)[0])
            before = gamma_dinsar_input_signature(plan)
            plan.inputs.map_dem.write_bytes(b"changed DEM")
            self.assertNotEqual(gamma_dinsar_input_signature(plan), before)

    def test_exact_commands_and_manifest_publish_cumulative_displacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pair = common_fixture.GammaTimeSeriesCommonTests.pairs[0]
            _, cfg = self._config(Path(directory), pair=pair)
            plan = build_gamma_dinsar_plan(load_gamma_dinsar_config(cfg)[0])
            fake = _FakeGamma()
            summary = run_gamma_dinsar(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.status, "complete")
            self.assertEqual(
                [call[0] for call in fake.calls],
                ["dispmap", "geocode_back", "geocode_back", "rasdt_pwr", "rasdt_pwr"],
            )
            self.assertEqual(Path(fake.calls[0][1]), plan.pair.corrected_phase)
            self.assertFalse((plan.case.output_dir / "diff_tab").exists())
            manifest = json.loads(
                (plan.case.output_dir / "timeseries_manifest.json").read_text()
            )
            self.assertEqual(manifest["method"], "gamma_dinsar")
            self.assertEqual(manifest["deformation_quantity"], "cumulative_displacement")
            self.assertEqual(manifest["products"]["radar"]["units"], "meter")
            self.assertEqual(manifest["products"]["geocoded"]["units"], "meter")
            self.assertNotIn("velocity", json.dumps(manifest).lower())

    def test_failure_reuse_mismatch_and_figure_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pair = common_fixture.GammaTimeSeriesCommonTests.pairs[0]
            _, cfg = self._config(Path(directory), pair=pair)
            plan = build_gamma_dinsar_plan(load_gamma_dinsar_config(cfg)[0])
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                run_gamma_dinsar(
                    plan,
                    command_runner=_FakeGamma(fail_program="geocode_back"),
                    progress_sink=lambda _: None,
                )
            self.assertFalse(plan.case.output_dir.exists())
            self.assertFalse(plan.case.figure_dir.exists())

            run_gamma_dinsar(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            repeat = _FakeGamma()
            self.assertEqual(
                run_gamma_dinsar(plan, command_runner=repeat, progress_sink=lambda _: None).status,
                "complete",
            )
            self.assertTrue(repeat.calls)
            changed = _FakeGamma()
            self.assertEqual(
                run_gamma_dinsar(
                    replace(plan, case=replace(plan.case, display_max=0.2)),
                    command_runner=changed,
                    progress_sink=lambda _: None,
                ).status,
                "complete",
            )
            self.assertTrue(changed.calls)
            science = plan.case.output_dir / "cumulative_los_displacement"
            content = science.read_bytes()
            missing = plan.case.figure_dir / "cumulative_los_displacement.radar.bmp"
            missing.unlink()
            repair = _FakeGamma()
            self.assertEqual(
                run_gamma_dinsar(plan, command_runner=repair, progress_sink=lambda _: None).status,
                "complete",
            )
            self.assertIn("dispmap", [call[0] for call in repair.calls])
            self.assertEqual(science.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
