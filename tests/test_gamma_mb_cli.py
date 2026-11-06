"""CLI dry-run test for GAMMA mb."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from geodesy_analysis.insar.time_series.gamma.mb.cli import main

import test_gamma_mb as mb_fixture


class GammaMbCliTests(unittest.TestCase):
    def test_dry_run_exposes_flags_subdirectories_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, cfg = mb_fixture.GammaMbTests()._config(Path(directory))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(cfg), "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["method"], "gamma_mb")
            self.assertEqual(payload["pair_count"], 2)
            self.assertEqual(payload["epoch_count"], 3)
            self.assertTrue(payload["generate_displacement"])
            self.assertTrue(payload["generate_geocoded_displacement"])
            for key in (
                "output_dir",
                "figure_dir",
                "log_dir",
                "intermediate_dir",
                "displacement_dir",
                "geocoded_displacement_dir",
            ):
                self.assertTrue(Path(payload[key]).is_absolute())


if __name__ == "__main__":
    unittest.main()
