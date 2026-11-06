"""Shared manifest/network preparation tests for GAMMA time-series methods."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.time_series.gamma.common import (
    load_gamma_time_series_inputs,
    write_gamma_diff_tab,
    write_gamma_itab,
    write_gamma_rmli_tab,
)


class GammaTimeSeriesCommonTests(unittest.TestCase):
    pairs = ("20231027-20231226", "20231226-20240107")
    dates = ("20231027", "20231226", "20240107")

    @staticmethod
    def _float(path: Path, values=(1.0, 2.0, 3.0, 4.0)) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.asarray(values, dtype=">f4").tofile(path)
        return path

    @staticmethod
    def _write_manifest(path: Path, payload: dict[str, object]) -> tuple[Path, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def _fixture(self, root: Path, *, declare_geometry: bool = True):
        project = root / "project"
        project.mkdir()
        processing = project / "S1/ASCENDING_128/GAMMA_mb"

        stack_dir = project / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET"
        assets = []
        for date in self.dates:
            data = stack_dir / f"RSLC/{date}.rslc"
            data.parent.mkdir(parents=True, exist_ok=True)
            data.write_bytes(b"complex")
            parameter = data.with_suffix(".rslc.par")
            parameter.write_text("range_samples: 4\nazimuth_lines: 4\n")
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": data.relative_to(stack_dir).as_posix(),
                    "parameter_path": parameter.relative_to(stack_dir).as_posix(),
                }
            )
        stack, stack_digest = self._write_manifest(
            stack_dir / "registered_stack.json",
            {
                "schema_version": 2,
                "status": "complete",
                "sensor": "sentinel1",
                "backend": {"name": "gamma"},
                "geometry_type": "radar_grid",
                "reference_date": "20231226",
                "dates": list(self.dates),
                "polarizations": ["VV"],
                "assets": assets,
            },
        )

        baseline_dir = processing / "BASELINE_SELECTION/GAMMA"
        network = baseline_dir / "baseline_select_SBAS"
        network.parent.mkdir(parents=True)
        network.write_text(
            "20231027 20231226 64.0239 60\n"
            "20231226 20240107 -12.5 12\n",
            encoding="utf-8",
        )
        baseline, baseline_digest = self._write_manifest(
            baseline_dir / "baseline_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "backend": {"name": "gamma"},
                "case_id": "S1/ASCENDING_128",
                "network_path": network.name,
                "pair_count": 2,
                "polarization": "VV",
                "reference_date": "20231226",
                "registered_stack_project_path": stack.relative_to(project).as_posix(),
                "stack_digest": stack_digest,
            },
        )

        ifg_dir = processing / "INTERFEROGRAM_GENERATION/GAMMA"
        mli_assets = []
        for date in self.dates:
            data = self._float(ifg_dir / f"MLI/{date}.mli")
            parameter = data.with_suffix(".mli.par")
            parameter.write_text("range_samples: 2\nazimuth_lines: 2\n")
            mli_assets.append(
                {
                    "date": date,
                    "data_path": data.relative_to(ifg_dir).as_posix(),
                    "parameter_path": parameter.relative_to(ifg_dir).as_posix(),
                }
            )
        geo_dir = processing / "GEO/GAMMA"
        radar = self._float(geo_dir / "reference.wgs84.hgt")
        lookup = geo_dir / "reference.lt_fine"
        lookup.write_bytes(b"lookup")
        map_dem = self._float(geo_dir / "demcrop.dem", range(6))
        map_par = geo_dir / "demcrop.dem_par"
        map_par.write_text("width: 3\nnlines: 2\n", encoding="utf-8")
        ifg_payload: dict[str, object] = {
            "schema_version": 2,
            "status": "complete",
            "case_id": "S1/ASCENDING_128",
            "polarization": "VV",
            "reference_date": "20231226",
            "registered_stack_project_path": stack.relative_to(project).as_posix(),
            "stack_digest": stack_digest,
            "baseline_manifest_project_path": baseline.relative_to(project).as_posix(),
            "mli_assets": mli_assets,
            "radar_height_project_path": radar.relative_to(project).as_posix(),
            "pairs": [{"pair": name} for name in self.pairs],
        }
        if declare_geometry:
            ifg_payload.update(
                {
                    "lookup_table_project_path": lookup.relative_to(project).as_posix(),
                    "map_dem_segment_project_path": map_dem.relative_to(project).as_posix(),
                    "map_dem_segment_parameter_project_path": map_par.relative_to(project).as_posix(),
                }
            )
        ifg, ifg_digest = self._write_manifest(
            ifg_dir / "interferogram_manifest.json", ifg_payload
        )

        filtering, filtering_digest = self._write_manifest(
            processing / "FILTERING/NL_INSAR/filtering_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "nl_insar",
                "interferogram_manifest_project_path": ifg.relative_to(project).as_posix(),
                "interferogram_manifest_digest": ifg_digest,
            },
        )
        unwrapping, unwrapping_digest = self._write_manifest(
            processing / "UNWRAPPING/GAMMA_MCF/unwrapping_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "gamma_mcf",
                "filtering_manifest_project_path": filtering.relative_to(project).as_posix(),
                "filtering_manifest_digest": filtering_digest,
            },
        )
        detrending, detrending_digest = self._write_manifest(
            processing / "DETRENDING/GAMMA_QUAD/detrending_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "gamma_quad_detrending",
                "unwrapping_manifest_project_path": unwrapping.relative_to(project).as_posix(),
                "unwrapping_manifest_digest": unwrapping_digest,
                "filtering_manifest_project_path": filtering.relative_to(project).as_posix(),
                "filtering_manifest_digest": filtering_digest,
                "interferogram_manifest_project_path": ifg.relative_to(project).as_posix(),
                "interferogram_manifest_digest": ifg_digest,
            },
        )
        atmosphere_dir = processing / "ATMOSPHERE/NONE"
        atmosphere_pairs = []
        for name in self.pairs:
            corrected = self._float(atmosphere_dir / f"PAIRS/{name}/pair.atm.unw")
            atmosphere_pairs.append(
                {
                    "pair": name,
                    "corrected_phase_project_path": corrected.relative_to(project).as_posix(),
                }
            )
        atmosphere, atmosphere_digest = self._write_manifest(
            atmosphere_dir / "atmosphere_manifest.json",
            {
                "schema_version": 2,
                "status": "complete",
                "case_id": "S1/ASCENDING_128",
                "method": "none",
                "grid": {"width": 2, "lines": 2},
                "detrending_manifest_project_path": detrending.relative_to(project).as_posix(),
                "detrending_manifest_digest": detrending_digest,
                "unwrapping_manifest_project_path": unwrapping.relative_to(project).as_posix(),
                "unwrapping_manifest_digest": unwrapping_digest,
                "filtering_manifest_project_path": filtering.relative_to(project).as_posix(),
                "filtering_manifest_digest": filtering_digest,
                "interferogram_manifest_project_path": ifg.relative_to(project).as_posix(),
                "interferogram_manifest_digest": ifg_digest,
                "pair_count": len(atmosphere_pairs),
                "pairs": atmosphere_pairs,
            },
        )
        return {
            "project": project,
            "atmosphere": atmosphere,
            "atmosphere_digest": atmosphere_digest,
            "baseline_digest": baseline_digest,
            "lookup": lookup,
            "map_dem": map_dem,
            "map_par": map_par,
            "network": network,
            "ifg": ifg,
        }

    def _load(self, fixture, **overrides):
        arguments = {
            "project_root": fixture["project"],
            "atmosphere_manifest": fixture["atmosphere"],
            "pair_list": None,
            "lookup_table": None,
            "map_dem": None,
            "map_dem_parameter": None,
        }
        arguments.update(overrides)
        return load_gamma_time_series_inputs(**arguments)

    def test_loads_lineage_network_geometry_and_writes_exact_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            inputs = self._load(fixture)
            self.assertEqual(inputs.atmosphere_manifest_digest, fixture["atmosphere_digest"])
            self.assertEqual(inputs.baseline_manifest_digest, fixture["baseline_digest"])
            self.assertEqual([item.name for item in inputs.pairs], list(self.pairs))
            self.assertEqual(
                [item.temporal_baseline_days for item in inputs.pairs], [60.0, 12.0]
            )
            self.assertEqual(inputs.acquisition_dates, self.dates)
            self.assertEqual(inputs.reference_date, "20231226")
            self.assertEqual((inputs.width, inputs.lines), (2, 2))
            self.assertEqual(inputs.lookup_table, fixture["lookup"])
            self.assertEqual(inputs.map_dem, fixture["map_dem"])
            self.assertEqual(inputs.map_dem_parameter, fixture["map_par"])

            staging = Path(directory) / "staging"
            staging.mkdir()
            diff = write_gamma_diff_tab(inputs, staging / "diff_tab")
            rmli = write_gamma_rmli_tab(inputs, staging / "RMLI_tab")
            itab = write_gamma_itab(inputs, staging / "itab")
            self.assertEqual(
                diff.read_text().splitlines(),
                [
                    f"{inputs.pairs[0].corrected_phase} 60",
                    f"{inputs.pairs[1].corrected_phase} 12",
                ],
            )
            self.assertEqual(
                rmli.read_text().splitlines(),
                [
                    f"{asset.data} {asset.parameter}"
                    for asset in inputs.mli_assets
                ],
            )
            self.assertEqual(itab.read_text().splitlines(), ["1 2 1 1", "2 3 2 1"])

    def test_explicit_pair_list_preserves_order_and_records_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            pair_list = Path(directory) / "selected_pairs.txt"
            pair_list.write_text(
                f"{self.pairs[1]}\n{self.pairs[0]}\n", encoding="utf-8"
            )
            inputs = self._load(fixture, pair_list=pair_list)
            self.assertEqual([item.name for item in inputs.pairs], list(reversed(self.pairs)))
            self.assertEqual(
                inputs.pair_list_digest,
                hashlib.sha256(pair_list.read_bytes()).hexdigest(),
            )

    def test_old_manifest_requires_explicit_geometry_and_accepts_matching_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory), declare_geometry=False)
            with self.assertRaisesRegex(ValueError, "lookup_table"):
                self._load(fixture)
            inputs = self._load(
                fixture,
                lookup_table=fixture["lookup"],
                map_dem=fixture["map_dem"],
                map_dem_parameter=fixture["map_par"],
            )
            self.assertEqual(inputs.lookup_table, fixture["lookup"])

    def test_missing_selected_pair_duplicate_or_zero_baseline_fail_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            pair_list = Path(directory) / "selected_pairs.txt"
            pair_list.write_text("20231027-20240107\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selected pair"):
                self._load(fixture, pair_list=pair_list)

        for network_text, message in (
            (
                "20231027 20231226 1 60\n20231027 20231226 2 60\n",
                "duplicate",
            ),
            (
                "20231027 20231226 1 0\n20231226 20240107 2 12\n",
                "non-zero",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory))
                fixture["network"].write_text(network_text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    self._load(fixture)

    def test_symlinked_or_conflicting_explicit_geometry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            symlink = fixture["lookup"].with_name("linked.lt_fine")
            symlink.symlink_to(fixture["lookup"])
            with self.assertRaisesRegex(ValueError, "symlink"):
                self._load(fixture, lookup_table=symlink)
            other = fixture["lookup"].with_name("other.lt_fine")
            other.write_bytes(b"other")
            with self.assertRaisesRegex(ValueError, "conflicts"):
                self._load(fixture, lookup_table=other)

    def test_lineage_digest_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            payload = json.loads(fixture["atmosphere"].read_text())
            payload["interferogram_manifest_digest"] = "0" * 64
            fixture["atmosphere"].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                self._load(fixture)


if __name__ == "__main__":
    unittest.main()
