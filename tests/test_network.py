"""Tests for Analysis-owned interferogram network parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.network import (
    GammaNetworkRecord,
    read_gamma_network_records,
    read_interferogram_pairs,
)


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

    def test_reads_strict_gamma_network_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "baseline_select"
            source.write_text(
                "# master slave perpendicular temporal_days\n"
                "20231027 20231226 64.0239 60\n",
                encoding="utf-8",
            )

            self.assertEqual(
                read_gamma_network_records(source),
                (
                    GammaNetworkRecord(
                        master="20231027",
                        slave="20231226",
                        perpendicular_baseline=64.0239,
                        temporal_baseline_days=60.0,
                    ),
                ),
            )
            self.assertEqual(
                read_gamma_network_records(source)[0].name,
                "20231027-20231226",
            )

    def test_strict_records_reject_duplicate_invalid_and_nonfinite_rows(self) -> None:
        cases = (
            (
                "20231027 20231226 64 60\n20231027 20231226 65 60\n",
                "duplicate",
            ),
            ("20231327 20231226 64 60\n", "YYYYMMDD"),
            ("20231027 20231226 nan 60\n", "finite"),
            ("20231027 20231226 64 inf\n", "finite"),
            ("20231027 20231226 64\n", "four columns"),
        )
        for content, message in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "baseline_select"
                source.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    read_gamma_network_records(source)


if __name__ == "__main__":
    unittest.main()
