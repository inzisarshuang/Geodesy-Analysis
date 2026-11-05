"""Planning, command, publication, and recovery tests for GAMMA quad detrending."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.detrending.gamma.quad.config import (
    load_gamma_quad_detrend_config,
)
from geodesy_analysis.insar.detrending.gamma.quad.plan import (
    build_gamma_quad_detrend_plan,
)
from geodesy_analysis.insar.detrending.gamma.quad.runner import (
    run_gamma_quad_detrend,
)
from tests.test_gamma_mcf_plan import GammaMcfPlanTests


class _FakeGammaQuad:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_on = fail_on

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append(argv)
        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        Path(stdout_path).write_text("stdout\n", encoding="utf-8")
        Path(stderr_path).write_text("", encoding="utf-8")
        if argv[0] == self.fail_on:
            raise RuntimeError(f"forced {argv[0]} failure")
        if argv[0] == "create_diff_par":
            Path(argv[3]).write_text("diff parameters\n", encoding="utf-8")
        elif argv[0] == "quad_fit":
            Path(argv[6]).write_text("fit data\n", encoding="utf-8")
        elif argv[0] == "quad_sub":
            np.arange(6, dtype=">f4").tofile(argv[3])
        elif argv[0] == "rasdt_pwr":
            Path(argv[-1]).write_bytes(b"BMquicklook")


class GammaQuadDetrendTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        filtering_path, interferogram_path, _ = GammaMcfPlanTests()._project(root)
        filtering = json.loads(filtering_path.read_text(encoding="utf-8"))
        names = [item["pair"] for item in filtering["pairs"]]
        filtering_digest = hashlib.sha256(filtering_path.read_bytes()).hexdigest()
        unwrap_dir = filtering_path.parents[2] / "UNWRAPPING" / "GAMMA_MCF"
        unwrap_dir.mkdir(parents=True)
        pairs = []
        for name in names:
            pair_dir = unwrap_dir / "pairs" / name
            pair_dir.mkdir(parents=True)
            np.arange(6, dtype=">f4").tofile(pair_dir / "pair.tflt.filt.unw")
            pairs.append(
                {
                    "pair": name,
                    "unwrapped_path": f"pairs/{name}/pair.tflt.filt.unw",
                }
            )
        manifest = {
            "case_id": "S1/ASCENDING_128",
            "filtering_manifest_digest": filtering_digest,
            "filtering_manifest_project_path": filtering_path.relative_to(root).as_posix(),
            "grid": {"lines": 2, "width": 3},
            "method": "gamma_mcf",
            "pair_count": len(pairs),
            "pairs": pairs,
            "schema_version": 2,
            "status": "complete",
        }
        (unwrap_dir / "unwrapping_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        config = root / "config/analysis/gamma_quad_detrending.cfg"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "[project]\n"
            f"root = {root}\n"
            "[defaults]\n"
            "coherence_threshold = 0.15\n"
            "trend_model = 0\n"
            "intensity_background = true\n"
            "[case:main]\n"
            "case_root = S1/ASCENDING_128\n"
            "unwrapping_manifest = "
            "S1/ASCENDING_128/ANALYSIS/UNWRAPPING/GAMMA_MCF/"
            "unwrapping_manifest.json\n",
            encoding="utf-8",
        )
        return config

    def _plan(self, root: Path):
        config = self._project(root)
        (case,) = load_gamma_quad_detrend_config(config)
        return build_gamma_quad_detrend_plan(case)

    def test_builds_manifest_lineage_and_discovers_shared_pair_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._project(root)
            (case,) = load_gamma_quad_detrend_config(config)
            plan = build_gamma_quad_detrend_plan(case)
            self.assertEqual((plan.width, plan.lines), (3, 2))
            self.assertEqual(len(plan.pairs), 2)
            self.assertEqual(plan.case.coherence_threshold, 0.15)
            self.assertEqual(plan.case.trend_model, 0)
            self.assertEqual(
                plan.case.output_dir,
                root / "S1/ASCENDING_128/ANALYSIS/DETRENDING/GAMMA_QUAD",
            )
            pair_list = root / "S1/ASCENDING_128/pairs.txt"
            selected_name = plan.pairs[1].name
            pair_list.write_text(f"{selected_name}\n", encoding="utf-8")
            (case,) = load_gamma_quad_detrend_config(config)
            plan = build_gamma_quad_detrend_plan(case)
            self.assertEqual([item.name for item in plan.pairs], [selected_name])
            self.assertEqual(plan.available_pair_count, 2)
            self.assertEqual(plan.case.pair_list, pair_list)

    def test_rejects_shared_pair_not_present_in_mcf_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._project(root)
            pair_list = root / "S1/ASCENDING_128/pairs.txt"
            pair_list.write_text("20231226-20240212\n", encoding="utf-8")
            (case,) = load_gamma_quad_detrend_config(config)
            with self.assertRaisesRegex(ValueError, "no unwrapped input"):
                build_gamma_quad_detrend_plan(case)

    def test_commands_and_products_follow_gamma_quad_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            fake = _FakeGammaQuad()
            result = run_gamma_quad_detrend(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(result.status, "complete")
            self.assertEqual(result.pair_count, 2)
            self.assertEqual(
                [call[0] for call in fake.calls],
                [
                    "create_diff_par",
                    "quad_fit",
                    "quad_sub",
                    "rasdt_pwr",
                ]
                * 2,
            )
            self.assertEqual(
                fake.calls[0][1:3],
                (str(plan.pairs[0].master_mli_parameter), "-"),
            )
            self.assertEqual(fake.calls[0][4:], ("1", "0"))
            self.assertEqual(
                fake.calls[1][1],
                str(plan.pairs[0].unwrapped),
            )
            self.assertEqual(fake.calls[1][3:5], ("-", "-"))
            self.assertEqual(fake.calls[1][-1], "0")
            self.assertEqual(fake.calls[2][1], str(plan.pairs[0].unwrapped))
            self.assertEqual(fake.calls[2][-2:], ("0", "0"))
            self.assertEqual(fake.calls[3][1], fake.calls[2][3])
            self.assertEqual(fake.calls[3][2], str(plan.pairs[0].master_mli))
            self.assertEqual(fake.calls[3][3], str(plan.width))
            manifest = json.loads(
                (plan.case.output_dir / "detrending_manifest.json").read_text()
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["method"], "gamma_quad_detrending")
            self.assertEqual(manifest["pair_count"], 2)
            self.assertEqual(
                manifest["pairs"][0]["products"]["detrended_unwrapped"],
                f"pairs/{plan.pairs[0].name}/pair.quad.unw",
            )
            self.assertTrue(
                (
                    plan.case.visualization_dir
                    / f"{plan.pairs[0].name}.quad.unw.bmp"
                ).is_file()
            )

    def test_background_free_quicklook_can_be_selected_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._project(root)
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "intensity_background = true",
                    "intensity_background = false",
                ),
                encoding="utf-8",
            )
            (case,) = load_gamma_quad_detrend_config(config)
            self.assertFalse(case.intensity_background)
            plan = build_gamma_quad_detrend_plan(case)
            fake = _FakeGammaQuad()
            run_gamma_quad_detrend(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            quicklook = fake.calls[3]
            self.assertEqual(quicklook[0], "rasdt_pwr")
            self.assertEqual(quicklook[2], "-")
            self.assertEqual(quicklook[3], str(plan.width))
            manifest = json.loads(
                (plan.case.output_dir / "detrending_manifest.json").read_text()
            )
            provenance = json.loads(
                (plan.case.output_dir / "provenance.json").read_text()
            )
            self.assertFalse(manifest["intensity_background"])
            self.assertIsNone(provenance["commands"]["quicklook"]["background"])

    def test_intensity_background_defaults_to_true_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self._project(Path(directory))
            original = config.read_text(encoding="utf-8")
            config.write_text(
                original.replace("intensity_background = true\n", ""),
                encoding="utf-8",
            )
            (case,) = load_gamma_quad_detrend_config(config)
            self.assertTrue(case.intensity_background)

            config.write_text(
                original.replace("intensity_background = true", "intensity_background = yes"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must be true or false"):
                load_gamma_quad_detrend_config(config)

    def test_incomplete_existing_scientific_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            plan.case.output_dir.mkdir(parents=True)
            previous = plan.case.output_dir / "previous-result"
            previous.write_text("keep me", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "completion manifest is missing"):
                run_gamma_quad_detrend(
                    plan,
                    command_runner=_FakeGammaQuad(fail_on="quad_sub"),
                    progress_sink=lambda _: None,
                )
            self.assertEqual(previous.read_text(encoding="utf-8"), "keep me")
            self.assertFalse(
                (plan.case.output_dir / "detrending_manifest.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
