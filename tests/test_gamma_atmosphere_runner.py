"""Transactional command-contract tests for GAMMA atmosphere correction."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.atmosphere.gamma.plan import build_gamma_atmosphere_plan
from geodesy_analysis.insar.atmosphere.gamma.runner import run_gamma_atmosphere

from test_gamma_atmosphere_plan import GammaAtmospherePlanTests as _AtmosphereFixture


class _FakeGamma:
    def __init__(self, *, fail_pair: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_pair = fail_pair

    @staticmethod
    def _float(path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.asarray((1.0, 2.0, 3.0, 4.0), dtype=">f4").tofile(target)

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(item) for item in command)
        self.calls.append(argv)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(f"{argv[0]} complete\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        if self.fail_pair is not None and any(self.fail_pair in value for value in argv):
            raise RuntimeError(f"synthetic failure for {self.fail_pair}")
        program = argv[0]
        if program == "create_diff_par":
            Path(argv[3]).write_text(
                "range_samples: 2\nazimuth_lines: 2\n", encoding="utf-8"
            )
        elif program == "atm_mod_2d":
            Path(argv[7]).write_bytes(b"a0")
            Path(argv[8]).write_bytes(b"a1")
        elif program == "atm_sim_2d":
            self._float(argv[5])
        elif program == "sub_phase":
            self._float(argv[4])
        elif program == "fspf":
            self._float(argv[2])
        elif program == "poly_mask":
            self._float(argv[2])
        elif program == "float_math":
            self._float(argv[3])
        elif program == "rasdt_pwr":
            Path(argv[-1]).write_bytes(b"quicklook")
        return None


class GammaAtmosphereRunnerTests(unittest.TestCase):
    def _plan(self, root: Path, method: str):
        fixture = _AtmosphereFixture()
        return build_gamma_atmosphere_plan(fixture._case(root, method=method))

    def test_exact_method_command_contracts_and_manifest_publication(self) -> None:
        expected = {
            "none": ["rasdt_pwr"],
            "gamma_atm_mod_2d_auto": [
                "create_diff_par",
                "atm_mod_2d",
                "atm_sim_2d",
                "sub_phase",
                "rasdt_pwr",
                "rasdt_pwr",
            ],
            "gamma_atm_mod_2d_polygon": [
                "poly_mask",
                "rasdt_pwr",
                "create_diff_par",
                "atm_mod_2d",
                "atm_sim_2d",
                "sub_phase",
                "poly_mask",
                "float_math",
                "rasdt_pwr",
                "rasdt_pwr",
            ],
            "gamma_fspf_atm_mod_2d": [
                "fspf",
                "create_diff_par",
                "atm_mod_2d",
                "atm_sim_2d",
                "sub_phase",
                "rasdt_pwr",
                "rasdt_pwr",
            ],
        }
        for method, per_pair in expected.items():
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                plan = self._plan(Path(directory), method)
                fake = _FakeGamma()
                summary = run_gamma_atmosphere(
                    plan, command_runner=fake, progress_sink=lambda _: None
                )
                self.assertEqual(summary.status, "complete")
                self.assertEqual(summary.pair_count, 2)
                programs = [call[0] for call in fake.calls]
                self.assertEqual(programs, per_pair * 2)
                manifest = json.loads(
                    (plan.case.output_dir / "atmosphere_manifest.json").read_text()
                )
                self.assertEqual(manifest["schema_version"], 2)
                self.assertEqual(manifest["status"], "complete")
                self.assertEqual(manifest["method"], method)
                self.assertEqual(manifest["grid"], {"lines": 2, "width": 2})
                self.assertEqual(
                    [item["pair"] for item in manifest["pairs"]],
                    [pair.name for pair in plan.pairs],
                )
                if method == "none":
                    self.assertEqual(manifest["required_products"], ["provenance.json"])
                    self.assertEqual(
                        len(manifest["required_external_products"]), len(plan.pairs)
                    )
                    self.assertFalse((plan.case.output_dir / "PAIRS").exists())
                else:
                    self.assertFalse(manifest["required_external_products"])
                    for item in manifest["pairs"]:
                        corrected = plan.case.output_dir / item["corrected_phase_path"]
                        self.assertEqual(corrected.stat().st_size, 16)

    def test_polygon_keeps_interior_and_merges_complementary_products(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self._plan(Path(directory), "gamma_atm_mod_2d_polygon")
            fake = _FakeGamma()
            run_gamma_atmosphere(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            first_pair_calls = fake.calls[:10]
            masks = [call for call in first_pair_calls if call[0] == "poly_mask"]
            self.assertEqual(masks[0][-2:], ("1", "0"))
            self.assertEqual(masks[1][-2:], ("0", "0"))
            merge = next(call for call in first_pair_calls if call[0] == "float_math")
            self.assertEqual(merge[4:], ("2", "0", "-", "-", "-", "-", "-", "1"))
            model = next(call for call in first_pair_calls if call[0] == "atm_mod_2d")
            self.assertTrue(model[5].endswith("outside.mask.bmp"))

    def test_later_pair_failure_publishes_nothing_and_preserves_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self._plan(Path(directory), "gamma_atm_mod_2d_auto")
            fake = _FakeGamma(fail_pair=plan.pairs[1].name)
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                run_gamma_atmosphere(
                    plan, command_runner=fake, progress_sink=lambda _: None
                )
            self.assertFalse(plan.case.output_dir.exists())
            self.assertFalse(plan.case.figure_dir.exists())
            failed = list(plan.case.log_dir.parent.glob(f"{plan.case.log_dir.name}.failed-logs-*"))
            self.assertEqual(len(failed), 1)
            self.assertTrue(any(path.stat().st_size for path in failed[0].glob("*.log")))

    def test_matching_output_skips_and_changed_parameters_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self._plan(Path(directory), "gamma_atm_mod_2d_auto")
            run_gamma_atmosphere(
                plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
            )
            fake = _FakeGamma()
            summary = run_gamma_atmosphere(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])
            changed_case = replace(plan.case, fit_window_range=64)
            with self.assertRaisesRegex(RuntimeError, "signature changed"):
                run_gamma_atmosphere(
                    replace(plan, case=changed_case),
                    command_runner=_FakeGamma(),
                    progress_sink=lambda _: None,
                )

    def test_missing_quicklook_is_repaired_without_science_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = self._plan(Path(directory), "gamma_atm_mod_2d_auto")
            run_gamma_atmosphere(
                plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
            )
            science = plan.case.output_dir / "PAIRS" / plan.pairs[0].name / "pair.atm.unw"
            content = science.read_bytes()
            missing = plan.case.figure_dir / f"{plan.pairs[0].name}.corrected.bmp"
            missing.unlink()
            fake = _FakeGamma()
            summary = run_gamma_atmosphere(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.status, "figures_repaired")
            self.assertEqual([call[0] for call in fake.calls], ["rasdt_pwr"])
            self.assertEqual(science.read_bytes(), content)
            self.assertTrue(missing.is_file())


if __name__ == "__main__":
    unittest.main()
