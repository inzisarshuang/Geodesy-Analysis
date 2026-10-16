"""CLI and packaging contracts for GAMMA MCF."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geodesy_analysis.insar.unwrapping.gamma.mcf.cli import main
from tests.test_gamma_mcf_plan import GammaMcfPlanTests


class GammaMcfCliTests(unittest.TestCase):
    def test_dry_run_prints_default_without_creating_mask_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, config = GammaMcfPlanTests()._project(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--config", str(config), "--case", "main", "--dry-run"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["method"], "gamma_mcf")
            self.assertEqual(payload["filtering_method"], "nl_insar")
            self.assertEqual(payload["pair_count"], 2)
            self.assertEqual(payload["output_dir"], str(root / "S1/ASCENDING_128/ANALYSIS/UNWRAPPING/GAMMA_MCF"))
            self.assertFalse((root / "S1/ASCENDING_128/ANALYSIS/UNWRAPPING").exists())
            self.assertFalse((root / "S1/ASCENDING_128/LOG").exists())

    def test_omitted_case_runs_all_and_errors_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, config = GammaMcfPlanTests()._project(root)
            text = config.read_text(encoding="utf-8")
            config.write_text(text + text.split("[case:main]", 1)[1].replace("\n", "\n", 1).join(("\n[case:second]", "")), encoding="utf-8")
            with patch("geodesy_analysis.insar.unwrapping.gamma.mcf.cli.run_gamma_mcf") as runner:
                self.assertEqual(main(["--config", str(config)]), 0)
            self.assertEqual(runner.call_count, 2)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["--config", str(config), "--case", "missing", "--dry-run"]), 2)

    def test_public_entry_example_and_docs_are_discoverable(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        self.assertIn("geodesy-analysis-gamma-mcf", (repository / "pyproject.toml").read_text(encoding="utf-8"))
        example = (repository / "config_examples/gamma_mcf_unwrapping.cfg").read_text(encoding="utf-8")
        for value in ("filtering_manifest", "reference_mode", "reference_range", "mcf_mode", "output_dir", "凭据安全"):
            self.assertIn(value, example)
        workflow = (repository / "docs/workflows/gamma_insar.md").read_text(encoding="utf-8")
        self.assertLess(workflow.index("geodesy-analysis-filtering"), workflow.index("geodesy-analysis-gamma-mcf"))


if __name__ == "__main__":
    unittest.main()
