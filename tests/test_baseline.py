"""Standalone numerical tests for baseline analysis."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar import baseline


class BaselineTests(unittest.TestCase):
    """Preserve pair order, solved baselines, connectivity, and light imports."""

    def test_import_does_not_load_matplotlib(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import geodesy_analysis.insar.baseline; "
                "assert 'matplotlib' not in sys.modules",
            ],
            cwd=tempfile.gettempdir(),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reads_pair_order_and_solves_signed_perpendicular_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "baseline_select_SBAS_060"
            source.write_text(
                "20200101-20200113 10 12\n"
                "20200113 20200125 -3 12\n"
                "20200101-20200125 7 24\n",
                encoding="utf-8",
            )
            rows = baseline.read_baseline_file(str(source))
        self.assertEqual(
            rows,
            [
                (20200101, 20200113, 10.0, 12.0),
                (20200113, 20200125, -3.0, 12.0),
                (20200101, 20200125, 7.0, 24.0),
            ],
        )
        dates = baseline.collect_dates(rows)
        self.assertEqual(dates, [20200101, 20200113, 20200125])
        self.assertEqual(
            baseline.solve_perpendicular_baselines(rows, dates, 20200101),
            {20200101: 0.0, 20200113: 10.0, 20200125: 7.0},
        )

    def test_network_selection_keeps_tree_connected_and_source_ordered(self) -> None:
        rows = [
            (20200101, 20200113, 10.0, 12.0),
            (20200113, 20200125, -3.0, 12.0),
            (20200101, 20200125, 7.0, 24.0),
        ]
        selected, dates, tree = baseline.select_interferogram_network(
            rows, [0.9, 0.8, 0.1], coefficient=1.0
        )
        self.assertEqual(dates, [20200101, 20200113, 20200125])
        np.testing.assert_array_equal(tree, [0, 1])
        np.testing.assert_array_equal(selected, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
