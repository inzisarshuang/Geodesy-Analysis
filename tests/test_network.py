"""Tests for Analysis-owned interferogram network parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.network import read_interferogram_pairs


class InterferogramPairTests(unittest.TestCase):
    """Verify supported manifests preserve pair order."""

    def test_reads_hyphenated_and_two_column_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "shortbaseline"
            source.write_text(
                "# network\n"
                "20240101-20240113 1.0 12\n"
                "20240113 20240125 -2.0 12\n"
                "unrelated row\n"
                "20240125-20240206\n",
                encoding="utf-8",
            )

            self.assertEqual(
                read_interferogram_pairs(source),
                [
                    "20240101-20240113",
                    "20240113-20240125",
                    "20240125-20240206",
                ],
            )

    def test_missing_file_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "missing"
            with self.assertRaises(FileNotFoundError):
                read_interferogram_pairs(source)


if __name__ == "__main__":
    unittest.main()
