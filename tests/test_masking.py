"""Standalone numerical and file tests for InSAR masking."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar import masking


class MaskingTests(unittest.TestCase):
    """Preserve mask values, bounded amplitude statistics, and atomic image I/O."""

    def test_threshold_combination_and_relaxation_keep_binary_semantics(self) -> None:
        coherence = np.array([[0.2, 0.5], [0.8, 1.0]], dtype=np.float32)
        high = masking.coherence_mask(coherence, 0.5)
        low = masking.coherence_mask(coherence, 0.8, keep_if_ge=False)
        np.testing.assert_array_equal(high, [[0, 1], [1, 1]])
        np.testing.assert_array_equal(low, [[1, 1], [1, 0]])
        np.testing.assert_array_equal(
            masking.combine_masks([high, low], "and"), [[0, 1], [1, 0]]
        )
        np.testing.assert_array_equal(
            masking.relax_amplitude_mask(high, np.array([[1, 1], [0, 0]])),
            [[0, 1], [1, 1]],
        )

    def test_coherence_mask_rejects_nonfinite_values(self) -> None:
        coherence = np.array([[np.nan, np.inf], [0.4, 0.8]], dtype=np.float32)
        np.testing.assert_array_equal(
            masking.coherence_mask(coherence, 0.5), [[0, 0], [0, 1]]
        )

    def test_mask_image_roundtrip_preserves_shape_and_binary_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mask.bmp"
            expected = np.array([[0, 1, 0], [1, 1, 0]], dtype=np.uint8)
            masking.write_mask(expected, str(output))
            actual = masking.read_mask(str(output), 2, 3)
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(list(output.parent.glob(".mask.*")), [])

    def test_amplitude_statistics_ignore_nonpositive_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.mli"
            second = root / "second.mli"
            np.array([[1.0, 0.0], [3.0, 4.0]], dtype=">f4").tofile(first)
            np.array([[3.0, 2.0], [0.0, 4.0]], dtype=">f4").tofile(second)

            mean, standard_deviation, count, dispersion = masking.amplitude_statistics(
                [str(first), str(second)], 2, 2, block_rows=1
            )

            np.testing.assert_allclose(mean, [[2.0, 2.0], [3.0, 4.0]])
            np.testing.assert_allclose(standard_deviation, [[1.0, 0.0], [0.0, 0.0]])
            np.testing.assert_array_equal(count, [[2, 1], [1, 2]])
            self.assertAlmostEqual(dispersion[0, 0], 0.5)
            self.assertTrue(np.isnan(dispersion[0, 1:]).all())
            self.assertTrue(np.isnan(dispersion[1]).all())


if __name__ == "__main__":
    unittest.main()
