"""Tests for cross-stage validation and GAMMA interferogram planning."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.insar.interferogram_generation.gamma.models import (
    GammaInterferogramCase,
)
from geodesy_analysis.insar.interferogram_generation.gamma.plan import (
    build_gamma_interferogram_plan,
    read_baseline_manifest,
)


class GammaInterferogramPlanTests(unittest.TestCase):
    """Pin identity checks, pair ordering, and sensor-specific filter flags."""

    dates = ("20231214", "20231226", "20240107")

    def _stack(self, root: Path, *, sensor: str = "sentinel1") -> tuple[Path, str]:
        stack = root / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET"
        data_dir = stack / "RSLC"
        data_dir.mkdir(parents=True)
        assets = []
        for date in self.dates:
            data = data_dir / f"{date}.rslc"
            parameter = data_dir / f"{date}.rslc.par"
            data.write_bytes(b"complex")
            parameter.write_text(
                "range_samples: 100\nazimuth_lines: 40\n", encoding="utf-8"
            )
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": str(data.relative_to(stack)),
                    "parameter_path": str(parameter.relative_to(stack)),
                }
            )
        manifest = stack / "registered_stack.json"
        manifest.write_text(
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
        return manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()

    def _baseline(
        self,
        root: Path,
        digest: str,
        *,
        network_text: str = "20231226 20240107 10 12\n20231214 20231226 -4 12\n",
        reference_date: str = "20231226",
        polarization: str = "VV",
        network_path: str = "baseline_select_SBAS",
        schema_version: int = 2,
    ) -> Path:
        directory = root / "S1/ASCENDING_128/ANALYSIS/BASELINE_SELECTION/GAMMA"
        directory.mkdir(parents=True)
        if network_path != "missing":
            (directory / network_path).write_text(network_text, encoding="utf-8")
        manifest = directory / "baseline_manifest.json"
        payload = {
            "schema_version": schema_version,
            "status": "complete",
            "stack_digest": digest,
            "polarization": polarization,
            "reference_date": reference_date,
            "network_type": "SBAS",
            "network_path": network_path,
            "pair_count": len(
                [line for line in network_text.splitlines() if line.strip()]
            ),
            "provenance_path": "provenance.json",
        }
        if schema_version == 2:
            payload.update(
                {
                    "backend": {"name": "gamma"},
                    "case_id": "S1/ASCENDING_128",
                    "registered_stack_project_path": (
                        "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/"
                        "registered_stack.json"
                    ),
                }
            )
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return manifest

    def _case(
        self,
        root: Path,
        stack: Path,
        baseline: Path,
        *,
        spectral_filter: str = "auto",
    ) -> GammaInterferogramCase:
        radar_height = root / "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim"
        radar_height.parent.mkdir(parents=True, exist_ok=True)
        radar_height.write_bytes(b"height")
        return GammaInterferogramCase(
            paths=bind_analysis_case(root, "ascending", "S1/ASCENDING_128"),
            registered_stack=stack,
            baseline_manifest=baseline,
            polarization="VV",
            range_looks=10,
            azimuth_looks=2,
            radar_height=radar_height,
            spectral_filter=spectral_filter,
            create_offset_range_start=0,
            create_offset_azimuth_start=0,
            create_offset_range_window=32,
            create_offset_azimuth_window=32,
            create_offset_range_search=64,
            create_offset_azimuth_search=64,
            create_offset_correlation_threshold=0.35,
            coherence_range_window=5,
            coherence_azimuth_window=5,
            coherence_estimator=2,
            output_dir=root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA",
        )

    def test_preserves_network_order_and_resolves_sentinel1_auto_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, digest = self._stack(root)
            baseline = self._baseline(root, digest)
            plan = build_gamma_interferogram_plan(
                self._case(root, stack, baseline)
            )
            self.assertEqual(
                [pair.name for pair in plan.pairs],
                ["20231226-20240107", "20231214-20231226"],
            )
            self.assertEqual(
                (plan.spectral_filter_range, plan.spectral_filter_azimuth),
                (0, 0),
            )
            self.assertEqual(plan.baseline.network_type, "SBAS")
            self.assertEqual(plan.baseline.stack_digest, digest)

    def test_auto_is_on_for_other_sensors_and_explicit_policy_wins(self) -> None:
        combinations = (
            ("saocom", "auto", (1, 1)),
            ("sentinel1", "on", (1, 1)),
            ("saocom", "off", (0, 0)),
        )
        for sensor, policy, expected in combinations:
            with self.subTest(sensor=sensor, policy=policy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stack, digest = self._stack(root, sensor=sensor)
                baseline = self._baseline(root, digest)
                plan = build_gamma_interferogram_plan(
                    self._case(root, stack, baseline, spectral_filter=policy)
                )
                self.assertEqual(
                    (plan.spectral_filter_range, plan.spectral_filter_azimuth), expected
                )

    def test_rejects_cross_stage_identity_mismatches(self) -> None:
        mismatches = (
            ("digest", {"stack_digest": "0" * 64}, "stack_digest"),
            ("reference", {"reference_date": "20231214"}, "reference_date"),
            ("polarization", {"polarization": "HH"}, "polarization"),
        )
        for _, changes, message in mismatches:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stack, digest = self._stack(root)
                baseline = self._baseline(
                    root,
                    changes.get("stack_digest", digest),
                    **{key: value for key, value in changes.items() if key != "stack_digest"},
                )
                with self.assertRaisesRegex(ValueError, message):
                    build_gamma_interferogram_plan(self._case(root, stack, baseline))

    def test_digest_mismatch_is_reported_before_network_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, _ = self._stack(root)
            baseline = self._baseline(root, "wrong", network_path="missing")
            with self.assertRaisesRegex(ValueError, "stack_digest"):
                build_gamma_interferogram_plan(self._case(root, stack, baseline))

    def test_rejects_unknown_self_duplicate_and_reversed_pairs(self) -> None:
        networks = (
            ("20231214 20240201 1 1\n", "not present"),
            ("20231214 20231214 1 0\n", "self pair"),
            (
                "20231214 20231226 1 12\n20231214 20231226 1 12\n",
                "duplicate pair",
            ),
            (
                "20231214 20231226 1 12\n20231226 20231214 -1 12\n",
                "reversed pair",
            ),
        )
        for network, message in networks:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stack, digest = self._stack(root)
                baseline = self._baseline(root, digest, network_text=network)
                with self.assertRaisesRegex(ValueError, message):
                    build_gamma_interferogram_plan(self._case(root, stack, baseline))

    def test_rejects_manifest_pair_count_that_disagrees_with_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, digest = self._stack(root)
            baseline = self._baseline(root, digest)
            payload = json.loads(baseline.read_text(encoding="utf-8"))
            payload["pair_count"] = 99
            baseline.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pair_count"):
                build_gamma_interferogram_plan(self._case(root, stack, baseline))

    def test_baseline_reader_rejects_manifest_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, digest = self._stack(root)
            baseline = self._baseline(root, digest)
            payload = json.loads(baseline.read_text(encoding="utf-8"))
            payload["network_path"] = "../../outside"
            baseline.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "network path"):
                read_baseline_manifest(
                    baseline,
                    paths=self._case(root, stack, baseline).paths,
                    registered_stack=stack,
                )

    def test_schema_two_baseline_requires_matching_case_and_stack_identity(self) -> None:
        mutations = (
            ("case_id", "S1/DESCENDING_135", "case_id"),
            ("backend", {"name": "other"}, "backend"),
            (
                "registered_stack_project_path",
                "../outside.json",
                "registered_stack_project_path",
            ),
            (
                "registered_stack_project_path",
                "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/missing.json",
                "does not exist",
            ),
        )
        for key, value, message in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stack, digest = self._stack(root)
                baseline = self._baseline(root, digest)
                payload = json.loads(baseline.read_text(encoding="utf-8"))
                payload[key] = value
                baseline.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                    build_gamma_interferogram_plan(self._case(root, stack, baseline))

    def test_legacy_schema_one_baseline_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, digest = self._stack(root)
            baseline = self._baseline(root, digest, schema_version=1)
            plan = build_gamma_interferogram_plan(self._case(root, stack, baseline))
            self.assertEqual(plan.baseline.schema_version, 1)

    def test_rejects_missing_or_empty_radar_height(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack, digest = self._stack(root)
            baseline = self._baseline(root, digest)
            case = self._case(root, stack, baseline)
            case.radar_height.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "radar height"):
                build_gamma_interferogram_plan(case)
            case.radar_height.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "radar height"):
                build_gamma_interferogram_plan(case)


if __name__ == "__main__":
    unittest.main()
