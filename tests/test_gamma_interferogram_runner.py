"""Tests for transactional GAMMA interferogram execution and publication."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.insar.interferogram_generation.gamma.models import (
    GammaInterferogramCase,
)
from geodesy_analysis.insar.interferogram_generation.gamma.plan import (
    build_gamma_interferogram_plan,
)
from geodesy_analysis.insar.interferogram_generation.gamma.runner import (
    run_gamma_interferograms,
)
from geodesy_analysis.insar.interferogram_generation.gamma.publication import (
    interferogram_input_signature,
)


class _FakeGamma:
    """Create the output belonging to each GAMMA command."""

    def __init__(
        self,
        *,
        fail_program: str | None = None,
        omit_output_for: str | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_program = fail_program
        self.omit_output_for = omit_output_for

    def run(self, command, *, cwd, stdin_text, stdout_path, stderr_path):
        argv = tuple(str(value) for value in command)
        self.calls.append({"argv": argv, "cwd": Path(cwd), "stdin": stdin_text})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(f"{argv[0]} complete\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        program = argv[0]
        if program == self.fail_program:
            stderr_path.write_text("synthetic command failure\n", encoding="utf-8")
            raise RuntimeError(f"synthetic {program} failure")
        if program == self.omit_output_for:
            return None
        if program == "multi_look":
            Path(argv[3]).write_bytes(b"mli")
            Path(argv[4]).write_text(
                "range_samples: 10\nazimuth_lines: 4\n", encoding="utf-8"
            )
        elif program == "ave_image":
            Path(argv[3]).write_bytes(b"average")
        elif program == "create_offset":
            Path(argv[3]).write_text("interferogram_width: 10\n", encoding="utf-8")
        elif program == "SLC_intf":
            Path(argv[6]).write_bytes(b"interferogram")
        elif program == "base_init":
            Path(argv[5]).write_text("baseline\n", encoding="utf-8")
        elif program == "ph_slope_base":
            Path(argv[5]).write_bytes(b"flattened")
        elif program == "create_diff_par":
            Path(argv[3]).write_text(
                "range_samples: 10\nazimuth_lines: 4\n", encoding="utf-8"
            )
        elif program == "phase_sim_orb":
            Path(argv[5]).write_bytes(b"simulated")
        elif program == "sub_phase":
            Path(argv[4]).write_bytes(b"differential")
        elif program == "cc_wave":
            Path(argv[4]).write_bytes(b"coherence")
        elif program in {"raspwr", "rasmph", "rasdt_pwr"}:
            Path(argv[-1]).write_bytes(b"BMquicklook")
        return None


class GammaInterferogramRunnerTests(unittest.TestCase):
    """Pin command order, argument mapping, de-duplication, and publication."""

    dates = ("20231214", "20231226", "20240107")

    def _plan(self, root: Path, *, sensor: str = "sentinel1"):
        stack_dir = root / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET"
        asset_dir = stack_dir / "RSLC"
        asset_dir.mkdir(parents=True)
        assets = []
        for date in self.dates:
            data = asset_dir / f"{date}.rslc"
            parameter = asset_dir / f"{date}.rslc.par"
            data.write_bytes(b"complex")
            parameter.write_text(
                "range_samples: 100\nazimuth_lines: 8\n", encoding="utf-8"
            )
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": f"RSLC/{date}.rslc",
                    "parameter_path": f"RSLC/{date}.rslc.par",
                }
            )
        stack = stack_dir / "registered_stack.json"
        stack.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "sensor": sensor,
                    "backend": {"name": "gamma"},
                    "geometry_type": "radar_grid",
                    "reference_date": "20231226",
                    "dates": list(self.dates),
                    "polarizations": ["VV"],
                    "assets": assets,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        digest = hashlib.sha256(stack.read_bytes()).hexdigest()
        baseline_dir = root / "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "baseline_select_SBAS").write_text(
            "20231226 20240107 4 12\n20231214 20231226 -10 12\n",
            encoding="utf-8",
        )
        baseline = baseline_dir / "baseline_manifest.json"
        baseline.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "backend": {"name": "gamma"},
                    "case_id": "S1/ASCENDING_128",
                    "status": "complete",
                    "stack_digest": digest,
                    "polarization": "VV",
                    "reference_date": "20231226",
                    "network_type": "SBAS",
                    "network_path": "baseline_select_SBAS",
                    "pair_count": 2,
                    "provenance_path": "provenance.json",
                    "registered_stack_project_path": (
                        "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/"
                        "registered_stack.json"
                    ),
                }
            ),
            encoding="utf-8",
        )
        radar_height = root / "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/20231226.hgt_sim"
        radar_height.parent.mkdir(parents=True)
        radar_height.write_bytes(b"\0" * (10 * 4 * 4))
        case = GammaInterferogramCase(
            paths=bind_analysis_case(root, "ascending", "S1/ASCENDING_128"),
            registered_stack=stack,
            baseline_manifest=baseline,
            polarization="VV",
            range_looks=10,
            azimuth_looks=2,
            radar_height=radar_height,
            spectral_filter="auto",
            create_offset_range_start=3,
            create_offset_azimuth_start=-2,
            create_offset_range_window=48,
            create_offset_azimuth_window=24,
            create_offset_range_search=96,
            create_offset_azimuth_search=40,
            create_offset_correlation_threshold=0.45,
            coherence_range_window=7,
            coherence_azimuth_window=9,
            coherence_estimator=2,
            output_dir=root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
            visualization_dir=root / "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA",
        )
        return build_gamma_interferogram_plan(case)

    def _legacy_signature(self, plan) -> str:
        case = plan.case
        payload = {
            "azimuth_looks": case.azimuth_looks,
            "baseline_manifest": str(plan.baseline.source_path),
            "coherence": {
                "azimuth_window": case.coherence_azimuth_window,
                "estimator": case.coherence_estimator,
                "range_window": case.coherence_range_window,
            },
            "create_offset": {
                "azimuth_search": case.create_offset_azimuth_search,
                "azimuth_start": case.create_offset_azimuth_start,
                "azimuth_window": case.create_offset_azimuth_window,
                "correlation_threshold": case.create_offset_correlation_threshold,
                "range_search": case.create_offset_range_search,
                "range_start": case.create_offset_range_start,
                "range_window": case.create_offset_range_window,
            },
            "filter_flags": [
                plan.spectral_filter_range,
                plan.spectral_filter_azimuth,
            ],
            "pairs": [pair.name for pair in plan.pairs],
            "polarization": case.polarization,
            "radar_height": {
                "path": str(case.radar_height),
                "sha256": hashlib.sha256(case.radar_height.read_bytes()).hexdigest(),
            },
            "range_looks": case.range_looks,
            "reference_date": plan.stack.reference_date,
            "stack_digest": plan.stack.source_digest,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def test_executes_each_mli_once_then_each_pair_in_exact_core_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            fake = _FakeGamma()
            progress: list[str] = []
            summary = run_gamma_interferograms(
                plan,
                command_runner=fake,
                progress_sink=progress.append,
            )

            programs = [call["argv"][0] for call in fake.calls]
            self.assertEqual(programs[:4], ["multi_look"] * 3 + ["ave_image"])
            core = [
                "create_offset",
                "SLC_intf",
                "base_init",
                "base_perp",
                "ph_slope_base",
                "create_diff_par",
                "phase_sim_orb",
                "sub_phase",
                "cc_wave",
            ]
            self.assertEqual(programs[4:13], core)
            self.assertEqual(programs[13:22], core)
            self.assertEqual(
                programs[22:],
                ["raspwr"] * 4 + ["rasmph", "rasdt_pwr"] * 2,
            )
            self.assertEqual(programs.count("multi_look"), len(self.dates))
            self.assertEqual(programs.count("ave_image"), 1)

            first_pair = plan.pairs[0].name
            first = fake.calls[4:13]
            self.assertEqual(
                first[0]["stdin"], f"{first_pair}\n3 -2\n48 24\n96 40\n0.45\n\n\n"
            )
            slc_intf = first[1]["argv"]
            self.assertEqual(slc_intf[-2:], ("0", "0"))
            self.assertEqual(slc_intf[7:9], ("10", "2"))
            cc_wave = first[-1]["argv"]
            self.assertEqual(cc_wave[-3:], ("7", "9", "2"))
            sub_phase = first[-2]["argv"]
            self.assertEqual(Path(sub_phase[1]).name, "pair.int")
            self.assertEqual(Path(sub_phase[3]).name, "pair.diff.par")

            output = plan.case.output_dir
            self.assertEqual(summary.status, "complete")
            self.assertEqual(summary.pair_count, 2)
            self.assertEqual(summary.acquisition_count, 3)
            for date in self.dates:
                self.assertTrue((output / "MLI" / f"{date}.mli").is_file())
                self.assertTrue((output / "MLI" / f"{date}.mli.par").is_file())
            for pair in plan.pairs:
                pair_dir = output / "PAIRS" / pair.name
                for name in (
                    "pair.int",
                    "pair.off",
                    "pair.baseline",
                    "pair.int.flt",
                    "pair.diff.par",
                    "pair.sim.topo.unw",
                    "pair.tflt",
                    "pair.cc",
                ):
                    self.assertTrue((pair_dir / name).is_file(), name)
            manifest = json.loads(
                (output / "interferogram_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["case_id"], "S1/ASCENDING_128")
            self.assertEqual(manifest["backend"], {"name": "gamma"})
            self.assertEqual(
                manifest["registered_stack_project_path"],
                "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            )
            self.assertEqual(
                manifest["baseline_manifest_project_path"],
                "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
            )
            self.assertEqual(
                manifest["radar_height_project_path"],
                "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/20231226.hgt_sim",
            )
            self.assertEqual(manifest["stack_digest"], plan.stack.source_digest)
            self.assertEqual(manifest["filter_flags"], {"azimuth": 0, "range": 0})
            self.assertEqual(manifest["looks"], {"azimuth": 2, "range": 10})
            self.assertEqual([item["date"] for item in manifest["mli_assets"]], list(self.dates))
            self.assertEqual([item["pair"] for item in manifest["pairs"]], [p.name for p in plan.pairs])
            visualization = plan.case.visualization_dir
            self.assertEqual(
                manifest["visualization_dir_project_path"],
                "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA",
            )
            self.assertEqual(
                manifest["average_mli_quicklook_project_path"],
                "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA/ave_mli.bmp",
            )
            self.assertEqual(
                [item["quicklook_project_path"] for item in manifest["mli_assets"]],
                [
                    f"S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA/{date}.mli.bmp"
                    for date in self.dates
                ],
            )
            for pair, item in zip(plan.pairs, manifest["pairs"]):
                self.assertEqual(
                    item["quicklooks"],
                    {
                        "coherence_project_path": (
                            "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/"
                            f"GAMMA/{pair.name}.cc.bmp"
                        ),
                        "phase_project_path": (
                            "S1/ASCENDING_128/VISUALIZATION/INTERFEROGRAM_GENERATION/"
                            f"GAMMA/{pair.name}.tflt.bmp"
                        ),
                    },
                )
            self.assertEqual(
                sorted(path.name for path in visualization.iterdir()),
                sorted(
                    [f"{date}.mli.bmp" for date in self.dates]
                    + ["ave_mli.bmp"]
                    + [
                        name
                        for pair in plan.pairs
                        for name in (f"{pair.name}.cc.bmp", f"{pair.name}.tflt.bmp")
                    ]
                ),
            )
            self.assertFalse((visualization / "PAIRS").exists())
            self.assertTrue(all(path.stat().st_size for path in visualization.iterdir()))
            provenance = json.loads(
                (output / "provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["schema_version"], 2)
            self.assertEqual(provenance["case_id"], "S1/ASCENDING_128")
            self.assertNotIn(str(root), json.dumps(manifest, sort_keys=True))
            self.assertNotIn(str(root), json.dumps(provenance, sort_keys=True))
            self.assertEqual(
                provenance["visualization_dir_project_path"],
                manifest["visualization_dir_project_path"],
            )
            self.assertIn('"status":"complete"', progress[-1])

    def test_radar_height_size_mismatch_stops_before_pair_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            plan.case.radar_height.write_bytes(b"wrong size")
            fake = _FakeGamma()
            with self.assertRaisesRegex(ValueError, "radar height grid size mismatch"):
                run_gamma_interferograms(
                    plan,
                    command_runner=fake,
                    progress_sink=lambda _: None,
                )
            self.assertEqual(
                [call["argv"][0] for call in fake.calls],
                ["multi_look", "multi_look", "multi_look", "ave_image"],
            )
            self.assertFalse(plan.case.output_dir.exists())

    def test_command_failure_and_missing_output_keep_logs_without_publication(self) -> None:
        scenarios = (
            (_FakeGamma(fail_program="SLC_intf"), RuntimeError, "synthetic"),
            (_FakeGamma(omit_output_for="SLC_intf"), ValueError, "did not create"),
            (_FakeGamma(omit_output_for="rasmph"), RuntimeError, "quicklook is missing"),
        )
        for fake, error_type, message in scenarios:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self._plan(root)
                with self.assertRaisesRegex(error_type, message):
                    run_gamma_interferograms(
                        plan,
                        command_runner=fake,
                        progress_sink=lambda _: None,
                    )
                self.assertFalse(plan.case.output_dir.exists())
                failures = list(
                    (
                        root
                        / "S1/ASCENDING_128/LOG/ANALYSIS/INTERFEROGRAM_GENERATION"
                    ).glob(
                        "GAMMA.failed-logs-*"
                    )
                )
                self.assertEqual(len(failures), 1)
                self.assertTrue(any(path.stat().st_size for path in failures[0].glob("*.log")))

    def test_matching_output_skips_and_changed_parameters_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            first = _FakeGamma()
            run_gamma_interferograms(
                plan,
                command_runner=first,
                progress_sink=lambda _: None,
            )
            second = _FakeGamma()
            summary = run_gamma_interferograms(
                plan,
                command_runner=second,
                progress_sink=lambda _: None,
            )
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(second.calls, [])

            changed_case = replace(plan.case, coherence_range_window=11)
            changed_plan = replace(plan, case=changed_case)
            with self.assertRaisesRegex(FileExistsError, "different inputs"):
                run_gamma_interferograms(
                    changed_plan,
                    command_runner=_FakeGamma(),
                    progress_sink=lambda _: None,
                )

    def test_legacy_schema_one_output_remains_restart_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_interferograms(
                plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
            )
            manifest_path = plan.case.output_dir / "interferogram_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1
            for key in (
                "backend",
                "baseline_manifest_project_path",
                "case_id",
                "radar_height_project_path",
                "registered_stack_project_path",
            ):
                manifest.pop(key)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            provenance_path = plan.case.output_dir / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.clear()
            provenance["input_signature"] = self._legacy_signature(plan)
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

            fake = _FakeGamma()
            summary = run_gamma_interferograms(
                plan, command_runner=fake, progress_sink=lambda _: None
            )
            self.assertEqual(summary.status, "skipped")
            self.assertEqual(fake.calls, [])

    def test_incomplete_existing_output_conflicts_instead_of_restarting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            plan.case.output_dir.mkdir(parents=True)
            with self.assertRaisesRegex(FileExistsError, "incomplete or invalid"):
                run_gamma_interferograms(
                    plan,
                    command_runner=_FakeGamma(),
                    progress_sink=lambda _: None,
                )

    def test_existing_manifest_with_wrong_pair_identity_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_interferograms(
                plan,
                command_runner=_FakeGamma(),
                progress_sink=lambda _: None,
            )
            manifest_path = plan.case.output_dir / "interferogram_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pairs"][0]["pair"] = "20000101-20000102"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "incomplete or invalid"):
                run_gamma_interferograms(
                    plan,
                    command_runner=_FakeGamma(),
                    progress_sink=lambda _: None,
                )

    def test_restart_rejects_changed_case_or_cross_stage_identity(self) -> None:
        mutations = (
            ("case_id", "S1/DESCENDING_135"),
            (
                "registered_stack_project_path",
                "S1/DESCENDING_135/PRE/GAMMA/RSLC_SUBSET/registered_stack.json",
            ),
            (
                "baseline_manifest_project_path",
                "S1/DESCENDING_135/ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json",
            ),
            (
                "radar_height_project_path",
                "S1/DESCENDING_135/PRE/GAMMA/GEOMETRY/20231226.hgt_sim",
            ),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self._plan(root)
                run_gamma_interferograms(
                    plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
                )
                manifest_path = plan.case.output_dir / "interferogram_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[key] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(FileExistsError, "incomplete or invalid"):
                    run_gamma_interferograms(
                        plan,
                        command_runner=_FakeGamma(),
                        progress_sink=lambda _: None,
                    )

    def test_legacy_manifest_repairs_only_quicklooks_without_touching_science(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_interferograms(
                plan,
                command_runner=_FakeGamma(),
                progress_sink=lambda _: None,
            )
            manifest_path = plan.case.output_dir / "interferogram_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("visualization_dir_project_path")
            manifest.pop("average_mli_quicklook_project_path")
            for item in manifest["mli_assets"]:
                item.pop("quicklook_project_path")
            for item in manifest["pairs"]:
                item.pop("quicklooks")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            provenance_path = plan.case.output_dir / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("visualization_dir_project_path")
            provenance.pop("quicklook_commands")
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            shutil.rmtree(plan.case.visualization_dir)
            science = {
                path: path.read_bytes()
                for path in plan.case.output_dir.rglob("*")
                if path.is_file() and path.name not in {"interferogram_manifest.json", "provenance.json"}
            }

            fake = _FakeGamma()
            summary = run_gamma_interferograms(
                plan, command_runner=fake, progress_sink=lambda _: None
            )

            self.assertEqual(summary.status, "repaired")
            self.assertEqual(
                [call["argv"][0] for call in fake.calls],
                ["raspwr"] * 4 + ["rasmph", "rasdt_pwr"] * 2,
            )
            self.assertEqual({path: path.read_bytes() for path in science}, science)

    def test_partial_visualization_with_unrelated_content_conflicts_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_interferograms(
                plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
            )
            missing = plan.case.visualization_dir / "ave_mli.bmp"
            missing.unlink()
            unrelated = plan.case.visualization_dir / "notes.txt"
            unrelated.write_text("keep\n", encoding="utf-8")

            fake = _FakeGamma()
            with self.assertRaisesRegex(FileExistsError, "unexpected entry"):
                run_gamma_interferograms(
                    plan, command_runner=fake, progress_sink=lambda _: None
                )
            self.assertEqual(fake.calls, [])
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep\n")

    def test_partial_expected_inventory_repairs_only_the_missing_bmp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            run_gamma_interferograms(
                plan, command_runner=_FakeGamma(), progress_sink=lambda _: None
            )
            missing = plan.case.visualization_dir / "ave_mli.bmp"
            missing.unlink()

            fake = _FakeGamma()
            summary = run_gamma_interferograms(
                plan, command_runner=fake, progress_sink=lambda _: None
            )

            self.assertEqual(summary.status, "repaired")
            self.assertEqual([call["argv"][0] for call in fake.calls], ["raspwr"])
            self.assertGreater(missing.stat().st_size, 0)

    def test_input_signature_is_project_location_independent(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_plan = self._plan(Path(first))
            second_plan = self._plan(Path(second))
            self.assertEqual(
                interferogram_input_signature(first_plan),
                interferogram_input_signature(second_plan),
            )


if __name__ == "__main__":
    unittest.main()
