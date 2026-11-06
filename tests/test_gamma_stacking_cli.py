"""CLI dry-run tests for GAMMA stacking."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from geodesy_analysis.insar.time_series.gamma.stacking.cli import main

import test_gamma_stacking as stacking_fixture


class GammaStackingCliTests(unittest.TestCase):
    def test_dry_run_exposes_paths_grid_and_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = stacking_fixture.GammaStackingTests()._config(Path(directory))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(cfg), "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["method"], "gamma_stacking")
            self.assertEqual(payload["grid"], {"lines": 2, "width": 2})
            self.assertEqual(
                payload["pairs"],
                ["20231027-20231226", "20231226-20240107"],
            )
            for key in ("atmosphere_manifest", "output_dir", "figure_dir", "log_dir"):
                self.assertTrue(Path(payload[key]).is_absolute())


if __name__ == "__main__":
    unittest.main()
