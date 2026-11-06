"""CLI dry-run test for single-pair GAMMA DInSAR."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from geodesy_analysis.insar.time_series.gamma.dinsar.cli import main

import test_gamma_dinsar as dinsar_fixture
import test_gamma_time_series_common as common_fixture


class GammaDinsarCliTests(unittest.TestCase):
    def test_dry_run_exposes_single_pair_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pair = common_fixture.GammaTimeSeriesCommonTests.pairs[0]
            _, cfg = dinsar_fixture.GammaDinsarTests()._config(
                Path(directory), pair=pair
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(cfg), "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["method"], "gamma_dinsar")
            self.assertEqual(payload["pair"], pair)
            self.assertEqual(payload["deformation_quantity"], "cumulative_displacement")
            for key in ("atmosphere_manifest", "output_dir", "figure_dir", "log_dir"):
                self.assertTrue(Path(payload[key]).is_absolute())


if __name__ == "__main__":
    unittest.main()
