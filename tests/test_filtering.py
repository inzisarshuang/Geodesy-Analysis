"""Standalone numerical tests for InSAR filtering."""

from __future__ import annotations

import unittest

import numpy as np

from geodesy_analysis.insar import filtering


class FilteringTests(unittest.TestCase):
    """Preserve filter defaults, complex composition, and mask behavior."""

    def test_public_functions_are_reexported_from_package(self) -> None:
        for name in (
            "resolve_filter_parameters",
            "estimate_boxcar_coherence",
            "nonlocal_insar_filter",
            "compose_filtered_interferogram",
        ):
            function = getattr(filtering, name)
            self.assertEqual(
                function.__module__,
                "geodesy_analysis.insar.filtering.methods.nl_insar",
            )

    def test_parameter_defaults_and_complex_composition(self) -> None:
        parameters = filtering.resolve_filter_parameters()
        self.assertEqual(
            {key: value for key, value in parameters.items() if key != "likelihood_h"},
            {
                "search_window": 13,
                "patch_size": 3,
                "minimum_looks": 80,
                "seed": 20260717,
            },
        )
        self.assertAlmostEqual(float(parameters["likelihood_h"]), 5.22)
        reflectivity = np.array([[2.0, 3.0], [4.0, 5.0]], dtype=np.float32)
        phase = np.array([[0.0, np.pi / 2], [np.pi, -np.pi / 2]], dtype=np.float32)
        valid = np.array([[True, True], [False, True]])
        result = filtering.compose_filtered_interferogram(reflectivity, phase, valid)
        self.assertEqual(result.dtype, np.complex64)
        np.testing.assert_allclose(np.abs(result[valid]), reflectivity[valid], rtol=1e-6)
        np.testing.assert_allclose(np.angle(result[valid]), phase[valid], atol=1e-6)
        self.assertEqual(result[1, 0], 0.0j)

    def test_boxcar_coherence_preserves_mask_and_closed_range(self) -> None:
        amplitude = np.ones((5, 5), dtype=np.float32)
        phase = np.zeros((5, 5), dtype=np.float32)
        valid = np.ones((5, 5), dtype=bool)
        valid[2, 2] = False
        coherence = filtering.estimate_boxcar_coherence(
            amplitude, amplitude, phase, window_size=3, valid_mask=valid
        )
        self.assertEqual(coherence.dtype, np.float32)
        self.assertEqual(coherence[2, 2], 0.0)
        self.assertTrue(np.all((coherence >= 0.0) & (coherence <= 1.0)))
        np.testing.assert_allclose(coherence[valid], 1.0, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
