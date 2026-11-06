"""Strict configuration and transactional execution tests for GAMMA stacking."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.time_series.gamma.stacking.config import (
    load_gamma_stacking_config,
)
from geodesy_analysis.insar.time_series.gamma.stacking.plan import (
    build_gamma_stacking_plan,
)
from geodesy_analysis.insar.time_series.gamma.stacking.runner import (
    run_gamma_stacking,
)
from geodesy_analysis.insar.time_series.gamma.stacking.publication import (
    gamma_stacking_input_signature,
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
        stdout_path.write_text("complete\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if argv[0] == self.fail_program:
            raise RuntimeError(f"synthetic {argv[0]} failure")
        if argv[0] == "stacking":
            for output in argv[3:6]:
                self._float(output, 4)
        elif argv[0] == "dispmap":
            self._float(argv[5], 4)
        elif argv[0] == "geocode_back":
            self._float(argv[4], 6)
        elif argv[0] == "rasdt_pwr":
            Path(argv[-1]).write_bytes(b"quicklook")
        return None


class GammaStackingTests(unittest.TestCase):
    def _config(self, root: Path, *, extra: str = ""):
        fixture = common_fixture.GammaTimeSeriesCommonTests()._fixture(root)
        cfg = root / "stacking.cfg"
        cfg.write_text(
            f"""[project]
root = {fixture['project']}

[case:ascending]
project = S1/ASCENDING_128
processing_root = S1/ASCENDING_128/GAMMA_mb
atmosphere_manifest = {fixture['atmosphere'].relative_to(fixture['project'])}
reference_range = 0
reference_azimuth = 0
reference_width = 2
reference_height = 2
{extra}
""",
            encoding="utf-8",
        )
        return fixture, cfg

    def test_loader_derives_method_paths_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, cfg = self._config(root)
            case = load_gamma_stacking_config(cfg)[0]
            processing = fixture["project"] / "S1/ASCENDING_128/GAMMA_mb"
            self.assertEqual(case.output_dir, processing / "TIMESERIES/STACKING")
            self.assertEqual(
                case.figure_dir, processing / "FIGURES/TIMESERIES/STACKING"
            )
            self.assertEqual(
                case.log_dir, processing / "LOG/ANALYSIS/TIMESERIES/STACKING"
            )
            self.assertEqual((case.reference_width, case.reference_height), (2, 2))
        for extra, message in (
            ("reference_range = -1", "non-negative"),
            ("reference_width = 0", "positive"),
            ("display_min = 1\ndisplay_max = 0", "display_min"),
            ("unknown = value", "unknown key"),
        ):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture, cfg = self._config(root)
                text = cfg.read_text()
                if extra.startswith("reference_range") or extra.startswith("reference_width"):
                    key = extra.split("=", 1)[0].strip()
                    text = "\n".join(
                        line for line in text.splitlines() if not line.startswith(f"{key} =")
                    ) + "\n"
                cfg.write_text(text + extra + "\n")
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_stacking_config(cfg)

    def test_plan_and_exact_commands_use_manifest_paths_and_reference_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, cfg = self._config(root)
            plan = build_gamma_stacking_plan(load_gamma_stacking_config(cfg)[0])
            self.assertEqual(
                [pair.name for pair in plan.inputs.pairs],
                list(common_fixture.GammaTimeSeriesCommonTests.pairs),
            )
            fake = _FakeGamma()
            summary = run_gamma_stacking(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.status, "complete")
            self.assertEqual(
                [call[0] for call in fake.calls],
                [
                    "stacking",
                    "dispmap",
                    "geocode_back",
                    "geocode_back",
                    "rasdt_pwr",
                    "rasdt_pwr",
                ],
            )
            stacking = fake.calls[0]
            self.assertEqual(stacking[-6:], ("0", "0", "2", "2", "-", "1"))
            self.assertEqual(Path(fake.calls[1][1]).name, "mean_phase_rate")
            self.assertNotIn(".atm.unw", " ".join(stacking))
            self.assertNotIn(".fill", " ".join(stacking))
            manifest = json.loads(
                (plan.case.output_dir / "timeseries_manifest.json").read_text()
            )
            self.assertEqual(manifest["method"], "gamma_stacking")
            self.assertEqual(manifest["products"]["mean_phase_rate"]["units"], "radian/day")
            self.assertEqual(manifest["products"]["mean_los_velocity"]["units"], "meter/day")
            self.assertEqual(manifest["reference_window"], {
                "range": 0, "azimuth": 0, "width": 2, "height": 2
            })

    def test_plan_rejects_reference_window_outside_grid_and_unknown_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, cfg = self._config(root)
            case = load_gamma_stacking_config(cfg)[0]
            with self.assertRaisesRegex(ValueError, "reference window"):
                build_gamma_stacking_plan(replace(case, reference_range=1, reference_width=2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, cfg = self._config(root)
            pair_list = root / "pairs.txt"
            pair_list.write_text("20231027-20240107\n")
            cfg.write_text(cfg.read_text() + f"pair_list = {pair_list}\n")
            with self.assertRaisesRegex(ValueError, "selected pair"):
                build_gamma_stacking_plan(load_gamma_stacking_config(cfg)[0])

    def test_signature_covers_geocoding_assets_and_command_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = self._config(Path(directory))
            plan = build_gamma_stacking_plan(load_gamma_stacking_config(cfg)[0])
            before = gamma_stacking_input_signature(plan)
            plan.inputs.lookup_table.write_bytes(b"changed lookup")
            self.assertNotEqual(gamma_stacking_input_signature(plan), before)

    def test_failure_reuse_mismatch_and_quicklook_repair_are_transactional(self) -> None:
        for program in ("stacking", "geocode_back"):
            with self.subTest(program=program), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, cfg = self._config(root)
                plan = build_gamma_stacking_plan(load_gamma_stacking_config(cfg)[0])
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    run_gamma_stacking(
                        plan,
                        command_runner=_FakeGamma(fail_program=program),
                        progress_sink=lambda _: None,
                    )
                self.assertFalse(plan.case.output_dir.exists())
                self.assertFalse(plan.case.figure_dir.exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, cfg = self._config(root)
            plan = build_gamma_stacking_plan(load_gamma_stacking_config(cfg)[0])
            run_gamma_stacking(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            fake = _FakeGamma()
            self.assertEqual(
                run_gamma_stacking(plan, command_runner=fake, progress_sink=lambda _: None).status,
                "skipped",
            )
            self.assertEqual(fake.calls, [])
            with self.assertRaisesRegex(RuntimeError, "signature changed"):
                run_gamma_stacking(
                    replace(plan, case=replace(plan.case, display_max=0.1)),
                    command_runner=_FakeGamma(),
                    progress_sink=lambda _: None,
                )
            science = plan.case.output_dir / "mean_los_velocity"
            original = science.read_bytes()
            missing = plan.case.figure_dir / "mean_los_velocity.radar.bmp"
            missing.unlink()
            repair = _FakeGamma()
            result = run_gamma_stacking(
                plan, command_runner=repair, progress_sink=lambda _: None
            )
            self.assertEqual(result.status, "figures_repaired")
            self.assertEqual([call[0] for call in repair.calls], ["rasdt_pwr"])
            self.assertEqual(science.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
