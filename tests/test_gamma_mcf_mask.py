"""Final-mask and reference-point tests for GAMMA MCF."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from geodesy_analysis.common.case_paths import bind_analysis_case
from geodesy_analysis.insar.masking import write_mask
from geodesy_analysis.insar.unwrapping.gamma.mcf.mask import (
    build_unwrapping_mask,
    resolve_reference_point,
    select_reference_point,
)
from geodesy_analysis.insar.unwrapping.gamma.mcf.models import (
    FilteringManifest,
    GammaMcfCase,
    GammaMcfPlan,
)


class GammaMcfMaskTests(unittest.TestCase):
    def _plan(self, root: Path, mean: np.ndarray, *, external: np.ndarray | None = None, operation: str = "and", reference_mode: str = "auto", reference_range: int | None = None, reference_azimuth: int | None = None) -> GammaMcfPlan:
        case_root = root / "S1/ASCENDING_128"
        case_root.mkdir(parents=True)
        filtering_path = case_root / "ANALYSIS/FILTERING/NL_INSAR/filtering_manifest.json"
        filtering_path.parent.mkdir(parents=True)
        filtering_path.write_text("{}", encoding="utf-8")
        mean_path = filtering_path.parent / "coh_ave.coh"
        mean.astype(">f4").tofile(mean_path)
        external_path = None
        if external is not None:
            external_path = case_root / "config/analysis/external.bmp"
            external_path.parent.mkdir(parents=True)
            write_mask(external, str(external_path))
        paths = bind_analysis_case(root, "main", "S1/ASCENDING_128")
        case = GammaMcfCase(
            paths=paths,
            filtering_manifest=filtering_path,
            mcf_mode=0,
            reference_mode=reference_mode,
            reference_range=reference_range,
            reference_azimuth=reference_azimuth,
            coherence_threshold=0.5,
            external_mask=external_path,
            mask_operation=operation,
            output_dir=case_root / "ANALYSIS/UNWRAPPING/GAMMA_MCF",
        )
        filtering = FilteringManifest(filtering_path, "digest", "nl_insar", filtering_path, "upstream", mean_path)
        dummy = case_root / "dummy"
        dummy.write_bytes(b"x")
        return GammaMcfPlan(case, filtering, (), mean.shape[1], mean.shape[0], mean_path, (dummy,), dummy)

    def test_coherence_only_and_external_boolean_masks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mean = np.array([[0.2, 0.7, 0.8], [0.6, 0.1, 0.9]], dtype=np.float32)
            external = np.array([[1, 1, 0], [0, 1, 1]], dtype=np.uint8)
            plan = self._plan(root, mean, external=external, operation="and")
            products = build_unwrapping_mask(plan, root / "stage")
            np.testing.assert_array_equal(products.mask, [[0, 1, 0], [0, 0, 1]])
            self.assertEqual(products.valid_count, 2)
            self.assertTrue(products.final_mask.is_file())
            self.assertTrue(products.binary_mask.is_file())
            self.assertTrue(products.metadata.is_file())

    def test_empty_mask_and_external_grid_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, np.zeros((2, 3), dtype=np.float32))
            with self.assertRaisesRegex(ValueError, "empty"):
                build_unwrapping_mask(plan, root / "stage")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root, np.ones((2, 3), dtype=np.float32), external=np.ones((2, 2), dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, "Size mismatch"):
                build_unwrapping_mask(plan, root / "stage")

    def test_automatic_reference_is_first_masked_finite_maximum(self) -> None:
        mean = np.array([[0.9, 0.9], [0.8, np.nan]], dtype=np.float32)
        mask = np.array([[0, 1], [1, 1]], dtype=np.uint8)
        range_index, azimuth_index, coherence = select_reference_point(mean, mask)
        self.assertEqual((range_index, azimuth_index), (1, 0))
        self.assertAlmostEqual(coherence, 0.9)

    def test_manual_reference_requires_in_bounds_unmasked_finite_pixel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mean = np.array([[0.2, 0.7, 0.8], [0.6, 0.1, 0.9]], dtype=np.float32)
            plan = self._plan(root, mean, reference_mode="manual", reference_range=2, reference_azimuth=1)
            products = build_unwrapping_mask(plan, root / "stage")
            reference = resolve_reference_point(plan, products)
            self.assertEqual((reference.range_index, reference.azimuth_index, reference.command_range, reference.command_azimuth), (2, 1, 2, 1))
            for changed, message in (
                (replace(plan.case, reference_range=3), "outside"),
                (replace(plan.case, reference_range=1, reference_azimuth=1), "masked"),
            ):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    resolve_reference_point(replace(plan, case=changed), products)


if __name__ == "__main__":
    unittest.main()
