"""CLI tests for GAMMA atmosphere correction."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from geodesy_analysis.insar.atmosphere.gamma.cli import main

from test_gamma_atmosphere_plan import GammaAtmospherePlanTests as _AtmosphereFixture


class GammaAtmosphereCliTests(unittest.TestCase):
    def test_dry_run_prints_resolved_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = _AtmosphereFixture()._case(root)
            cfg = root / "atmosphere.cfg"
            cfg.write_text(
                f"""[project]
root = {case.project_root}

[case:ascending]
project = S1/ASCENDING_128
processing_root = S1/ASCENDING_128/GAMMA_mb
detrending_manifest = {case.detrending_manifest.relative_to(case.project_root)}
method = gamma_atm_mod_2d_auto
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(cfg), "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["case"], "ascending")
            self.assertEqual(payload["method"], "gamma_atm_mod_2d_auto")
            self.assertEqual(payload["grid"], {"lines": 2, "width": 2})
            self.assertEqual(payload["pair_count"], 2)
            self.assertEqual(payload["pairs"], list(_AtmosphereFixture.pairs))
            for key in (
                "detrending_manifest",
                "unwrapping_manifest",
                "filtering_manifest",
                "interferogram_manifest",
                "output_dir",
                "figure_dir",
                "log_dir",
                "auto_mask",
                "radar_height",
            ):
                self.assertTrue(Path(payload[key]).is_absolute(), key)

    def test_invalid_config_returns_validation_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory) / "invalid.cfg"
            cfg.write_text("[project]\nroot = /missing\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(["--config", str(cfg), "--dry-run"])
            self.assertEqual(code, 2)
            self.assertIn("ERROR:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
