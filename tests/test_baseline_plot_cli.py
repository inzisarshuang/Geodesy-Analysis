"""Tests for the source-neutral standalone baseline plotting entry point."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geodesy_analysis.insar.baseline_selection.common.plot_cli import main
from geodesy_analysis.insar.baseline_selection.common.plot_config import (
    load_baseline_plot_config,
)


class BaselinePlotCliTests(unittest.TestCase):
    """Preserve old plotting controls without rerunning GAMMA."""

    def _baseline(self, root: Path) -> Path:
        baseline = root / "ANALYSIS/BASELINE/baseline_select_SBAS"
        baseline.parent.mkdir(parents=True)
        baseline.write_text(
            "20231214 20231226 -10 12\n20231226 20240107 4 12\n",
            encoding="utf-8",
        )
        return baseline

    def _config(self, root: Path, baseline: Path) -> Path:
        config = root / "config/analysis/baseline_plot.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"""
[project]
root = {root}
[defaults]
title = From CFG
dpi = 150
figsize = 9, 5
y_top_extra = 30
y_bottom_extra = 2
font_family = TeX Gyre Heros
[case:ascending]
baseline = {baseline.relative_to(root)}
master_date = 20231226
orbit = 128
out_dir = FIGURES
out =
""",
            encoding="utf-8",
        )
        return config

    def test_cfg_and_cli_override_preserve_all_plot_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = self._baseline(root)
            config = self._config(root, baseline)
            cases = load_baseline_plot_config(config)
            self.assertEqual(cases[0].figsize, (9.0, 5.0))
            captured: dict[str, object] = {}

            def fake_plot(**kwargs):
                captured.update(kwargs)
                output = Path(kwargs["out_file"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"png")
                return str(output)

            with patch(
                "geodesy_analysis.insar.baseline_selection.common.plot_cli.plot_baseline_network",
                side_effect=fake_plot,
            ):
                code = main(
                    [
                        "--config", str(config), "--case", "ascending",
                        "--title", "From CLI", "--dpi", "200",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(captured["baseline_file"], str(baseline.resolve()))
            self.assertEqual(captured["master_date"], 20231226)
            self.assertEqual(captured["title"], "From CLI")
            self.assertEqual(captured["dpi"], 200)
            self.assertEqual(captured["figsize"], (9.0, 5.0))
            self.assertEqual(captured["y_top_extra"], 30.0)
            self.assertEqual(captured["y_bottom_extra"], 2.0)
            self.assertEqual(
                captured["out_file"],
                str((root / "FIGURES/baseline_select_SBAS_orbit128.png").resolve()),
            )

    def test_direct_mode_uses_positional_baseline_without_gamma(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = self._baseline(root)
            output = baseline.parent / "custom.png"
            with patch(
                "geodesy_analysis.insar.baseline_selection.common.plot_cli.plot_baseline_network",
                return_value=str(output),
            ) as plot:
                code = main(
                    [
                        str(baseline),
                        "--master-date", "20231226",
                        "--out", str(output),
                    ]
                )
            self.assertEqual(code, 0)
            plot.assert_called_once()
            self.assertEqual(plot.call_args.kwargs["baseline_file"], str(baseline.resolve()))

    def test_cfg_rejects_input_and_output_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside"
            outside.mkdir()
            baseline = outside / "baseline_select_SBAS"
            baseline.write_text("20231214 20231226 1 12\n", encoding="utf-8")
            config = root / "baseline_plot.cfg"
            config.write_text(
                f"""
[project]
root = {root}
[case:bad]
baseline = {baseline}
master_date = 20231226
out = {outside / 'plot.png'}
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "project root"):
                load_baseline_plot_config(config)

    def test_packaging_and_example_cfg_expose_standalone_plot(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        project = (repository / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("geodesy-analysis-baseline-plot", project)
        example = (repository / "config_examples/baseline_plot.cfg").read_text(
            encoding="utf-8"
        )
        for required in (
            "功能用途",
            "调用",
            "运行示例",
            "baseline",
            "master_date",
            "title",
            "dpi",
            "figsize",
            "font_family",
        ):
            with self.subTest(required=required):
                self.assertIn(required, example)


if __name__ == "__main__":
    unittest.main()
