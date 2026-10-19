"""CLI and packaging contracts for the filtering workflow."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from geodesy_analysis.insar.filtering.cli import main


class FilteringCliTests(unittest.TestCase):
    def _config(self, root: Path) -> Path:
        upstream = root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
        mli = []
        for date in ("20231226", "20240131"):
            data = upstream / "MLI" / f"{date}.mli"
            parameter = upstream / "MLI" / f"{date}.mli.par"
            data.parent.mkdir(parents=True, exist_ok=True)
            np.ones((2, 3), dtype=">f4").tofile(data)
            parameter.write_text("range_samples: 3\nazimuth_lines: 2\n", encoding="utf-8")
            mli.append({"date": date, "data_path": f"MLI/{date}.mli", "parameter_path": f"MLI/{date}.mli.par"})
        average_mli = upstream / "MLI/ave_mli"
        np.full((2, 3), 1.25, dtype=">f4").tofile(average_mli)
        pair = "20231226-20240131"
        tflt = upstream / "PAIRS" / pair / "pair.tflt"
        tflt.parent.mkdir(parents=True)
        np.ones((2, 3), dtype=">c8").tofile(tflt)
        (upstream / "interferogram_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "case_id": "S1/ASCENDING_128",
                    "mli_assets": mli,
                    "average_mli_path": "MLI/ave_mli",
                    "pairs": [{"pair": pair, "products": {"differential_interferogram": f"PAIRS/{pair}/pair.tflt"}}],
                }
            ),
            encoding="utf-8",
        )
        config = root / "config/analysis/insar_filtering.cfg"
        config.parent.mkdir(parents=True)
        cases = "\n".join(
            f"""[case:{name}]\ncase_root = S1/ASCENDING_128\ninterferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json\nmethod = {method}\n"""
            for name, method in (("nl", "nl_insar"), ("bm3d", "gamma_bm3d"), ("adf", "gamma_adf"))
        )
        config.write_text(f"[project]\nroot = {root}\n{cases}", encoding="utf-8")
        return config

    def test_selected_dry_run_prints_resolved_default_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--config", str(config), "--case", "bm3d", "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["case"], "bm3d")
            self.assertEqual(payload["method"], "gamma_bm3d")
            self.assertEqual(payload["pair_count"], 1)
            self.assertEqual(payload["grid"], {"lines": 2, "width": 3})
            self.assertEqual(payload["output_dir"], str(root / "S1/ASCENDING_128/ANALYSIS/FILTERING/GAMMA_BM3D"))
            self.assertFalse((root / "S1/ASCENDING_128/ANALYSIS/FILTERING").exists())
            self.assertFalse((root / "S1/ASCENDING_128/LOG").exists())

    def test_omitted_case_executes_all_configured_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(Path(directory))
            with patch("geodesy_analysis.insar.filtering.cli.run_filtering") as runner:
                code = main(["--config", str(config)])
            self.assertEqual(code, 0)
            self.assertEqual(runner.call_count, 3)
            self.assertEqual([call.args[0].case.name for call in runner.call_args_list], ["nl", "bm3d", "adf"])

    def test_unknown_case_and_operational_failure_use_distinct_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(Path(directory))
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["--config", str(config), "--case", "missing", "--dry-run"]), 2)
            with patch("geodesy_analysis.insar.filtering.cli.run_filtering", side_effect=RuntimeError("failed")), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["--config", str(config), "--case", "nl"]), 1)

    def test_public_command_example_and_docs_are_discoverable(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        self.assertIn("geodesy-analysis-filtering", (repository / "pyproject.toml").read_text(encoding="utf-8"))
        example = (
            repository / "config_examples/analysis/insar_filtering.cfg"
        ).read_text(encoding="utf-8")
        for value in ("nl_insar", "gamma_bm3d", "gamma_adf", "output_dir", "自动", "凭据安全"):
            self.assertIn(value, example)
        workflow = (repository / "docs/workflows/gamma_insar.md").read_text(encoding="utf-8")
        self.assertLess(workflow.index("interferogram_manifest.json"), workflow.index("geodesy-analysis-filtering"))


if __name__ == "__main__":
    unittest.main()
