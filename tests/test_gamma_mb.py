"""Strict and transactional tests for GAMMA mb SBAS/ISBAS."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from geodesy_analysis.insar.time_series.gamma.mb.config import load_gamma_mb_config
from geodesy_analysis.insar.time_series.gamma.mb.plan import build_gamma_mb_plan
from geodesy_analysis.insar.time_series.gamma.mb.runner import run_gamma_mb
from geodesy_analysis.insar.time_series.gamma.mb.publication import (
    gamma_mb_input_signature,
)

import test_gamma_time_series_common as common_fixture


class _FakeGamma:
    def __init__(self, *, fail_program: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_program = fail_program

    @staticmethod
    def _float(path: str | Path, count: int) -> None:
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
        if argv[0] == "mb":
            Path(argv[5]).write_text("1 2 1 1\n2 3 2 1\n")
            prefix = Path(argv[6])
            files = []
            for index in range(3):
                item = Path(f"{prefix}.{index + 1:03d}.diff")
                self._float(item, 4)
                files.append(item)
            Path(f"{prefix}.tab").write_text("".join(f"{item}\n" for item in files))
            self._float(argv[8], 4)
            self._float(argv[10], 4)
        elif argv[0] == "tpf_2d":
            prefix = Path(argv[4])
            files = []
            for index in range(3):
                item = Path(f"{prefix}.{index + 1:03d}.tpf")
                self._float(item, 4)
                files.append(item)
            Path(argv[5]).write_text("".join(f"{item}\n" for item in files))
        elif argv[0] == "ts_rate":
            self._float(argv[5], 4)
            self._float(argv[7], 4)
        elif argv[0] == "dispmap":
            self._float(argv[5], 4)
        elif argv[0] == "uchar2float":
            self._float(argv[2], 4)
        elif argv[0] == "geocode_back":
            self._float(argv[4], 6)
        elif argv[0] == "rasdt_pwr":
            Path(argv[-1]).write_bytes(b"quicklook")
        elif argv[0] == "mk_dispmap_2d":
            output_dir = Path(argv[4])
            output_dir.mkdir(parents=True, exist_ok=True)
            items = []
            for index in range(3):
                item = output_dir / f"displacement_{index + 1:03d}.bin"
                self._float(item, 4)
                items.append(item)
            Path(argv[7]).write_text("".join(f"{item}\n" for item in items))
        elif argv[0] == "mk_geo_data_all":
            output_dir = Path(argv[5])
            output_dir.mkdir(parents=True, exist_ok=True)
            for line in Path(argv[4]).read_text().splitlines():
                source = Path(line.split()[0])
                self._float(output_dir / f"{source.stem}_geo{source.suffix}", 6)
        return None


class GammaMbTests(unittest.TestCase):
    def _config(self, root: Path, *, extra: str = ""):
        fixture = common_fixture.GammaTimeSeriesCommonTests()._fixture(root)
        cfg = root / "mb.cfg"
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
mb_mode = 2
gamma = 0.5
dtmax = 70
generate_mean_geocoded = true
generate_displacement = true
generate_geocoded_displacement = true
{extra}
""",
            encoding="utf-8",
        )
        return fixture, cfg

    def test_loader_plan_and_output_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, cfg = self._config(root)
            case = load_gamma_mb_config(cfg)[0]
            plan = build_gamma_mb_plan(case)
            base = fixture["project"] / "S1/ASCENDING_128/GAMMA_mb/TIMESERIES/GAMMA_MB"
            self.assertEqual(case.output_dir, base)
            self.assertEqual(plan.intermediate_dir, base / "INTERMEDIATE")
            self.assertEqual(plan.displacement_dir, base / "DISPLACEMENT")
            self.assertEqual(plan.geocoded_displacement_dir, base / "DISPLACEMENT_GEO")
            self.assertEqual(len(plan.inputs.pairs), 2)
            self.assertEqual(len(plan.inputs.acquisition_dates), 3)
            self.assertIsNotNone(plan.inputs.final_mask)

    def test_strict_values_flags_and_optional_executable(self) -> None:
        invalid = (
            ("gamma = 0", "gamma"),
            ("dtmax = -1", "dtmax"),
            (
                "generate_displacement = false\ngenerate_geocoded_displacement = true",
                "requires generate_displacement",
            ),
        )
        for extra, message in invalid:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, cfg = self._config(root)
                text = cfg.read_text()
                for key in ("gamma", "dtmax", "generate_displacement", "generate_geocoded_displacement"):
                    if any(line.startswith(f"{key} =") for line in extra.splitlines()):
                        text = "\n".join(
                            line for line in text.splitlines() if not line.startswith(f"{key} =")
                        ) + "\n"
                cfg.write_text(text + extra + "\n")
                with self.assertRaisesRegex(ValueError, message):
                    load_gamma_mb_config(cfg)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "visdt_pwr.py"
            executable.write_text("#!/usr/bin/env python3\n")
            executable.chmod(0o755)
            _, cfg = self._config(root, extra=f"visdt_pwr = {executable}")
            self.assertEqual(load_gamma_mb_config(cfg)[0].visdt_pwr, executable)
            executable.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "executable"):
                load_gamma_mb_config(cfg)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_name = root / "visdt_pwr"
            wrong_name.write_text("#!/bin/sh\nexit 0\n")
            wrong_name.chmod(0o755)
            _, cfg = self._config(root, extra=f"visdt_pwr = {wrong_name}")
            with self.assertRaisesRegex(ValueError, "visdt_pwr.py"):
                load_gamma_mb_config(cfg)

    def test_explicit_visdt_directory_is_added_to_the_command_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tools/visdt_pwr.py"
            executable.parent.mkdir()
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            _, cfg = self._config(root, extra=f"visdt_pwr = {executable}")
            plan = build_gamma_mb_plan(load_gamma_mb_config(cfg)[0])
            fake = _FakeGamma()
            with patch(
                "geodesy_analysis.insar.time_series.gamma.mb.runner.SubprocessCommandRunner",
                return_value=fake,
            ) as factory:
                run_gamma_mb(plan, progress_sink=lambda _: None)
            environment = factory.call_args.kwargs["environment"]
            self.assertEqual(environment["PATH"].split(":", 1)[0], str(executable.parent))

    def test_signature_covers_geocoding_assets_and_command_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = self._config(Path(directory))
            plan = build_gamma_mb_plan(load_gamma_mb_config(cfg)[0])
            before = gamma_mb_input_signature(plan)
            plan.inputs.map_dem_parameter.write_bytes(b"changed DEM parameter")
            self.assertNotEqual(gamma_mb_input_signature(plan), before)

    def test_exact_commands_and_manifest_quantities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = self._config(Path(directory))
            plan = build_gamma_mb_plan(load_gamma_mb_config(cfg)[0])
            fake = _FakeGamma()
            summary = run_gamma_mb(plan, command_runner=fake, progress_sink=lambda _: None)
            self.assertEqual(summary.status, "complete")
            programs = [call[0] for call in fake.calls]
            self.assertEqual(programs[:4], ["mb", "tpf_2d", "ts_rate", "dispmap"])
            self.assertIn("uchar2float", programs)
            self.assertIn("mk_dispmap_2d", programs)
            self.assertIn("mk_geo_data_all", programs)
            self.assertTrue(all("/opt/GAMMA" not in " ".join(call) for call in fake.calls))
            mb_call = fake.calls[0]
            self.assertIn("/INTERMEDIATE/TS", mb_call[6])
            self.assertIn("/INTERMEDIATE/TS_tpf", fake.calls[1][4])
            manifest = json.loads(
                (plan.case.output_dir / "timeseries_manifest.json").read_text()
            )
            self.assertEqual(manifest["method"], "gamma_mb")
            self.assertEqual(manifest["products"]["mean_los_velocity"]["units"], "meter/year")
            self.assertEqual(manifest["displacement"]["quantity"], "cumulative_los_displacement")
            self.assertEqual(manifest["displacement"]["units"], "meter")
            self.assertEqual(manifest["epoch_count"], 3)
            dates_file = plan.case.output_dir / "images"
            self.assertEqual(dates_file.read_text().splitlines(), manifest["epochs"])
            self.assertIn("images", manifest["required_products"])
            for table, field in (
                ("DISPLACEMENT/displacement_tab", "paths"),
                ("DISPLACEMENT_GEO/displacement_geo_tab", "geocoded_paths"),
            ):
                tab = plan.case.output_dir / table
                paths = [(tab.parent / line).resolve() for line in tab.read_text().splitlines()]
                expected = [plan.case.output_dir / path for path in manifest["displacement"][field]]
                self.assertEqual(paths, expected)
                self.assertTrue(all(path.is_file() for path in paths))

    def test_failures_reuse_mismatch_and_quicklook_repair(self) -> None:
        for program in ("mb", "mk_geo_data_all"):
            with self.subTest(program=program), tempfile.TemporaryDirectory() as directory:
                _, cfg = self._config(Path(directory))
                plan = build_gamma_mb_plan(load_gamma_mb_config(cfg)[0])
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    run_gamma_mb(
                        plan,
                        command_runner=_FakeGamma(fail_program=program),
                        progress_sink=lambda _: None,
                    )
                self.assertFalse(plan.case.output_dir.exists())
                self.assertFalse(plan.case.figure_dir.exists())
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = self._config(Path(directory))
            plan = build_gamma_mb_plan(load_gamma_mb_config(cfg)[0])
            run_gamma_mb(plan, command_runner=_FakeGamma(), progress_sink=lambda _: None)
            repeated = _FakeGamma()
            self.assertEqual(
                run_gamma_mb(plan, command_runner=repeated, progress_sink=lambda _: None).status,
                "complete",
            )
            self.assertTrue(repeated.calls)
            changed = _FakeGamma()
            self.assertEqual(
                run_gamma_mb(
                    replace(plan, case=replace(plan.case, gamma=0.8)),
                    command_runner=changed,
                    progress_sink=lambda _: None,
                ).status,
                "complete",
            )
            self.assertTrue(changed.calls)
            science = plan.case.output_dir / "mean_los_velocity"
            before = science.read_bytes()
            missing = plan.case.figure_dir / "mean_los_velocity.radar.bmp"
            missing.unlink()
            repair = _FakeGamma()
            self.assertEqual(
                run_gamma_mb(plan, command_runner=repair, progress_sink=lambda _: None).status,
                "complete",
            )
            self.assertIn("mb", [call[0] for call in repair.calls])
            self.assertEqual(science.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
