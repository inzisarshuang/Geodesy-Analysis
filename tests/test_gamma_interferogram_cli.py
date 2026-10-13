"""CLI, packaging, and human-documentation contract tests."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geodesy_analysis.insar.interferogram_generation.gamma.cli import main


class GammaInterferogramCliTests(unittest.TestCase):
    """Keep dry-run read-only and public operation discoverable."""

    def _config(self, root: Path) -> Path:
        stack_dir = root / "PRE/RSLC"
        data_dir = stack_dir / "RSLC"
        data_dir.mkdir(parents=True)
        dates = ("20231214", "20231226")
        assets = []
        for date in dates:
            (data_dir / f"{date}.rslc").write_bytes(b"complex")
            (data_dir / f"{date}.rslc.par").write_text(
                "range_samples: 20\nazimuth_lines: 4\n", encoding="utf-8"
            )
            assets.append(
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": f"RSLC/{date}.rslc",
                    "parameter_path": f"RSLC/{date}.rslc.par",
                }
            )
        stack = stack_dir / "registered_stack.json"
        stack.write_text(
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        baseline_dir = root / "ANALYSIS/GAMMA/ascending/BASELINE"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "baseline_select_SBAS").write_text(
            "20231214 20231226 5 12\n", encoding="utf-8"
        )
        baseline = baseline_dir / "baseline_manifest.json"
        baseline.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "complete",
                    "stack_digest": hashlib.sha256(stack.read_bytes()).hexdigest(),
                    "polarization": "VV",
                    "reference_date": "20231226",
                    "network_type": "SBAS",
                    "network_path": "baseline_select_SBAS",
                    "pair_count": 1,
                    "provenance_path": "provenance.json",
                }
            ),
            encoding="utf-8",
        )
        height = root / "PRE/GEOMETRY/20231226.hgt_sim"
        height.parent.mkdir(parents=True)
        height.write_bytes(b"height")
        config = root / "config/analysis/gamma_interferogram.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"""
[project]
root = {root}
[case:ascending]
registered_stack = PRE/RSLC/registered_stack.json
baseline_manifest = ANALYSIS/GAMMA/ascending/BASELINE/baseline_manifest.json
polarization = VV
range_looks = 10
azimuth_looks = 2
radar_height = PRE/GEOMETRY/20231226.hgt_sim
spectral_filter = auto
output_dir = ANALYSIS/GAMMA/ascending/INTERFEROGRAM
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
                code = main(
                    ["--config", str(config), "--case", "ascending", "--dry-run"]
                )
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["case"], "ascending")
            self.assertEqual(payload["reference_date"], "20231226")
            self.assertEqual(payload["polarization"], "VV")
            self.assertEqual(payload["pair_count"], 1)
            self.assertEqual(payload["scene_count"], 2)
            self.assertEqual(payload["looks"], {"azimuth": 2, "range": 10})
            self.assertEqual(payload["spectral_filter"], "auto")
            self.assertEqual(payload["resolved_filter_flags"], {"azimuth": 0, "range": 0})
            self.assertEqual(payload["radar_height"], str(root / "PRE/GEOMETRY/20231226.hgt_sim"))
            self.assertFalse((root / "ANALYSIS/GAMMA/ascending/INTERFEROGRAM").exists())
            self.assertFalse((root / "LOG").exists())

    def test_configuration_and_operational_errors_have_distinct_exit_codes(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = main(["--config", "/definitely/missing/interferogram.cfg", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("ERROR:", error.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            config = self._config(Path(directory))
            with patch(
                "geodesy_analysis.insar.interferogram_generation.gamma.cli.run_gamma_interferograms",
                side_effect=RuntimeError("GAMMA failed"),
            ), contextlib.redirect_stderr(error):
                code = main(["--config", str(config), "--case", "ascending"])
            self.assertEqual(code, 1)

    def test_packaging_cfg_and_workflow_document_all_public_operations(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        project = (repository / "pyproject.toml").read_text(encoding="utf-8")
        for command in (
            "geodesy-analysis-gamma-baseline",
            "geodesy-analysis-baseline-plot",
            "geodesy-analysis-gamma-interferogram",
        ):
            with self.subTest(command=command):
                self.assertIn(command, project)

        example = (repository / "config_examples/gamma_interferogram.cfg").read_text(
            encoding="utf-8"
        )
        for required in (
            "功能用途",
            "查看帮助",
            "只检查",
            "正式运行",
            "参数说明",
            "容易出错",
            "结果保存",
            "日志",
            "完成判断",
            "重新运行",
            "凭据安全",
            "radar_height",
            "create_offset",
            "cc_wave",
        ):
            with self.subTest(required=required):
                self.assertIn(required, example)

        workflow = (repository / "docs/workflows/gamma_insar.md").read_text(
            encoding="utf-8"
        )
        ordered = (
            "registered_stack.json",
            "geodesy-analysis-gamma-baseline",
            "baseline_manifest.json",
            "geodesy-analysis-gamma-interferogram",
            "interferogram_manifest.json",
        )
        positions = [workflow.index(value) for value in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("/home/yilun/miniconda3/envs/envInSAR/bin/", workflow)
        self.assertIn("任意目录", workflow)


if __name__ == "__main__":
    unittest.main()
