"""CLI and documentation contract tests for GAMMA baseline selection."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.baseline_selection.gamma.cli import main


class GammaBaselineCliTests(unittest.TestCase):
    """Keep dry-run read-only and the public cfg fully explained."""

    def _config(self, root: Path) -> Path:
        stack = root / "S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET"
        data = stack / "RSLC"
        data.mkdir(parents=True)
        dates = ("20231214", "20231226")
        assets = []
        for date in dates:
            (data / f"{date}.rslc").write_bytes(b"complex")
            (data / f"{date}.rslc.par").write_text(
                "range_samples: 2\nazimuth_lines: 1\n", encoding="utf-8"
            )
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": f"RSLC/{date}.rslc",
                    "parameter_path": f"RSLC/{date}.rslc.par",
                }
            )
        manifest = stack / "registered_stack.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "sensor": "sentinel1",
                    "backend": {"name": "gamma"},
                    "geometry_type": "radar_grid",
                    "reference_date": "20231226",
                    "dates": list(dates),
                    "polarizations": ["VV"],
                    "assets": assets,
                }
            ),
            encoding="utf-8",
        )
        config = root / "config/analysis/gamma_baseline.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"""
[project]
root = {root}
[case:ascending]
case_root = S1/ASCENDING_128
registered_stack = S1/ASCENDING_128/PRE/GAMMA/RSLC_SUBSET/registered_stack.json
polarization = VV
network_type = SBAS
max_perpendicular_baseline = 300
max_temporal_baseline = 40
output_dir = S1/ASCENDING_128/ANALYSIS/GAMMA/BASELINE
""",
            encoding="utf-8",
        )
        return config

    def test_dry_run_prints_resolved_plan_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--config", str(config), "--case", "ascending", "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["case"], "ascending")
            self.assertEqual(payload["case_id"], "S1/ASCENDING_128")
            self.assertEqual(payload["reference_date"], "20231226")
            self.assertEqual(payload["network_type"], "SBAS")
            self.assertEqual(payload["polarization"], "VV")
            self.assertEqual(payload["max_perpendicular_baseline_m"], 300.0)
            self.assertEqual(payload["max_temporal_baseline_days"], 40.0)
            self.assertEqual(payload["scene_count"], 2)
            self.assertFalse(
                (root / "S1/ASCENDING_128/ANALYSIS").exists()
            )
            self.assertFalse((root / "S1/ASCENDING_128/LOG").exists())

    def test_configuration_error_returns_two(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = main(["--config", "/definitely/missing/gamma_baseline.cfg", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("ERROR:", error.getvalue())

    def test_packaging_and_example_cfg_expose_documented_entry(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        project = (repository / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("geodesy-analysis-gamma-baseline", project)
        example = (repository / "config_examples/gamma_baseline.cfg").read_text(
            encoding="utf-8"
        )
        for required in (
            "功能用途",
            "查看帮助",
            "只检查",
            "正式运行",
            "参数",
            "结果保存",
            "日志",
            "完成判断",
            "重新运行",
            "凭据",
        ):
            with self.subTest(required=required):
                self.assertIn(required, example)


if __name__ == "__main__":
    unittest.main()
