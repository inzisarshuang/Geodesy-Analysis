"""Lineage and publication identity tests for GAMMA atmosphere plans."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.insar.atmosphere.gamma.models import GammaAtmosphereCase
from geodesy_analysis.insar.atmosphere.gamma.plan import build_gamma_atmosphere_plan
from geodesy_analysis.insar.atmosphere.gamma.publication import (
    gamma_atmosphere_input_signature,
)


class GammaAtmospherePlanTests(unittest.TestCase):
    pairs = ("20231027-20231226", "20231226-20240107")

    @staticmethod
    def _raster(path: Path, values=(1.0, 2.0, 3.0, 4.0)) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.asarray(values, dtype=">f4").tofile(path)
        return path

    @staticmethod
    def _manifest(path: Path, payload: dict[str, object]) -> tuple[Path, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def _case(self, root: Path, *, method: str = "gamma_atm_mod_2d_auto"):
        project = root / "project"
        project.mkdir()
        case_root = project / "S1/ASCENDING_128"
        processing = case_root / "GAMMA_mb"

        ifg_dir = processing / "INTERFEROGRAM_GENERATION/GAMMA"
        mli_assets = []
        for date in ("20231027", "20231226", "20240107"):
            data = self._raster(ifg_dir / f"MLI/{date}.mli")
            parameter = data.with_suffix(".mli.par")
            parameter.write_text(
                "range_samples: 2\nazimuth_lines: 2\n", encoding="utf-8"
            )
            mli_assets.append(
                {
                    "date": date,
                    "data_path": data.relative_to(ifg_dir).as_posix(),
                    "parameter_path": parameter.relative_to(ifg_dir).as_posix(),
                }
            )
        radar = self._raster(processing / "GEO/GAMMA/reference.wgs84.hgt")
        ifg, ifg_digest = self._manifest(
            ifg_dir / "interferogram_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "mli_assets": mli_assets,
                "radar_height_project_path": radar.relative_to(project).as_posix(),
                "pairs": [{"pair": name} for name in self.pairs],
            },
        )

        filtering_dir = processing / "FILTERING/NL_INSAR"
        filter_pairs = []
        for name in self.pairs:
            coherence = self._raster(
                filtering_dir / f"pairs/{name}/pair.coh.filt",
                (0.4, 0.5, 0.6, 0.7),
            )
            filter_pairs.append(
                {
                    "pair": name,
                    "products": {
                        "filtered_coherence": coherence.relative_to(
                            filtering_dir
                        ).as_posix()
                    },
                }
            )
        filtering, filtering_digest = self._manifest(
            filtering_dir / "filtering_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "nl_insar",
                "grid": {"width": 2, "lines": 2},
                "interferogram_manifest_project_path": ifg.relative_to(
                    project
                ).as_posix(),
                "interferogram_manifest_digest": ifg_digest,
                "pair_count": len(filter_pairs),
                "pairs": filter_pairs,
            },
        )

        unwrap_dir = processing / "UNWRAPPING/GAMMA_MCF"
        auto_mask = unwrap_dir / "mask/final.mask.bmp"
        auto_mask.parent.mkdir(parents=True)
        auto_mask.write_bytes(b"mask")
        unwrap, unwrap_digest = self._manifest(
            unwrap_dir / "unwrapping_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "gamma_mcf",
                "grid": {"width": 2, "lines": 2},
                "filtering_manifest_project_path": filtering.relative_to(
                    project
                ).as_posix(),
                "filtering_manifest_digest": filtering_digest,
                "mask": {"final_mask_path": "mask/final.mask.bmp"},
                "pair_count": len(self.pairs),
                "pairs": [
                    {"pair": name, "unwrapped_path": f"pairs/{name}/pair.unw"}
                    for name in self.pairs
                ],
            },
        )

        detrend_dir = processing / "DETRENDING/GAMMA_QUAD"
        detrend_pairs = []
        for name in self.pairs:
            phase = self._raster(detrend_dir / f"pairs/{name}/pair.quad.unw")
            detrend_pairs.append(
                {
                    "pair": name,
                    "products": {
                        "detrended_unwrapped": phase.relative_to(
                            detrend_dir
                        ).as_posix()
                    },
                }
            )
        detrending, _ = self._manifest(
            detrend_dir / "detrending_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "gamma_quad_detrending",
                "grid": {"width": 2, "lines": 2},
                "unwrapping_manifest_project_path": unwrap.relative_to(
                    project
                ).as_posix(),
                "unwrapping_manifest_digest": unwrap_digest,
                "filtering_manifest_project_path": filtering.relative_to(
                    project
                ).as_posix(),
                "filtering_manifest_digest": filtering_digest,
                "interferogram_manifest_project_path": ifg.relative_to(
                    project
                ).as_posix(),
                "interferogram_manifest_digest": ifg_digest,
                "pair_count": len(detrend_pairs),
                "pairs": detrend_pairs,
            },
        )
        polygon = processing / "polygon.poly"
        polygon.write_text("0 0\n1 0\n1 1\n", encoding="utf-8")
        identity = {
            "none": "NONE",
            "gamma_atm_mod_2d_auto": "GAMMA_ATM_MOD_2D_AUTO",
            "gamma_atm_mod_2d_polygon": "GAMMA_ATM_MOD_2D_POLYGON",
            "gamma_fspf_atm_mod_2d": "GAMMA_FSPF_ATM_MOD_2D",
        }[method]
        paths = bind_analysis_case(
            project,
            "ascending",
            "S1/ASCENDING_128",
            "S1/ASCENDING_128/GAMMA_mb",
        )
        return GammaAtmosphereCase(
            paths=paths,
            detrending_manifest=detrending,
            method=method,
            output_dir=processing / f"ATMOSPHERE/{identity}",
            figure_dir=processing / f"FIGURES/ATMOSPHERE/{identity}",
            log_dir=processing / f"LOG/ANALYSIS/ATMOSPHERE/{identity}",
            intensity_background=True,
            fit_window_range=256,
            fit_window_azimuth=256,
            fit_step_range=128,
            fit_step_azimuth=128,
            height_correlation_threshold=0.1,
            polygon_file=(
                polygon if method == "gamma_atm_mod_2d_polygon" else None
            ),
            fspf_mode=2,
            fspf_window_size=256,
            fspf_overlap=4,
        )

    def test_resolves_complete_lineage_and_deterministic_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = self._case(Path(directory))
            plan = build_gamma_atmosphere_plan(case)
            self.assertEqual([item.name for item in plan.pairs], list(self.pairs))
            self.assertEqual((plan.width, plan.lines), (2, 2))
            self.assertEqual(plan.auto_mask.name, "final.mask.bmp")
            self.assertEqual(plan.radar_height.name, "reference.wgs84.hgt")
            self.assertEqual(plan.commands.create_diff_par, "create_diff_par")
            self.assertEqual(plan.commands.atm_mod_2d, "atm_mod_2d")
            self.assertEqual(plan.commands.atm_sim_2d, "atm_sim_2d")
            self.assertEqual(plan.commands.sub_phase, "sub_phase")
            for pair in plan.pairs:
                self.assertEqual(pair.detrended_phase.stat().st_size, 16)
                self.assertEqual(pair.coherence.stat().st_size, 16)
                self.assertEqual(pair.master_mli.stat().st_size, 16)
            first = gamma_atmosphere_input_signature(plan)
            second = gamma_atmosphere_input_signature(plan)
            self.assertEqual(first, second)
            self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_polygon_digest_changes_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = self._case(Path(directory), method="gamma_atm_mod_2d_polygon")
            plan = build_gamma_atmosphere_plan(case)
            initial = gamma_atmosphere_input_signature(plan)
            self.assertIsNotNone(plan.polygon_digest)
            assert case.polygon_file is not None
            case.polygon_file.write_text("0 0\n2 0\n2 2\n", encoding="utf-8")
            changed = build_gamma_atmosphere_plan(case)
            self.assertNotEqual(initial, gamma_atmosphere_input_signature(changed))

    def test_rejects_lineage_grid_digest_pair_product_and_polygon_failures(self) -> None:
        mutations = (
            ("case", lambda payload: payload.__setitem__("case_id", "S1/OTHER"), "case"),
            ("method", lambda payload: payload.__setitem__("method", "other"), "method"),
            ("grid", lambda payload: payload.__setitem__("grid", {"width": 3, "lines": 2}), "grid"),
            (
                "digest",
                lambda payload: payload.__setitem__("unwrapping_manifest_digest", "0" * 64),
                "digest",
            ),
            ("pairs", lambda payload: payload.__setitem__("pair_count", 1), "pair inventory"),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                case = self._case(Path(directory))
                payload = json.loads(case.detrending_manifest.read_text())
                mutate(payload)
                case.detrending_manifest.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    build_gamma_atmosphere_plan(case)

        with tempfile.TemporaryDirectory() as directory:
            case = self._case(Path(directory))
            payload = json.loads(case.detrending_manifest.read_text())
            missing = case.detrending_manifest.parent / payload["pairs"][0]["products"]["detrended_unwrapped"]
            missing.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                build_gamma_atmosphere_plan(case)

        with tempfile.TemporaryDirectory() as directory:
            case = self._case(Path(directory), method="gamma_atm_mod_2d_polygon")
            assert case.polygon_file is not None
            case.polygon_file.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "polygon"):
                build_gamma_atmosphere_plan(case)

    def test_rejects_destination_overlap_with_any_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = self._case(Path(directory))
            with self.assertRaisesRegex(ValueError, "overlap"):
                build_gamma_atmosphere_plan(
                    replace(case, output_dir=case.detrending_manifest.parent)
                )


if __name__ == "__main__":
    unittest.main()
