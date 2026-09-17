"""Standalone tests for GAMMA, target-table, and GNSS time-series analysis."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.timeseries import (
    TargetTimeSeries,
    align_series_on_common_dates,
    apply_temporal_reference,
    discover_gamma_mb_result,
    extract_target_timeseries,
    phase_to_los_displacement,
    project_enu_to_los,
    read_gnss_timeseries,
    read_target_timeseries_csv,
    write_target_timeseries_csv,
)


class GammaMBTimeSeriesTests(unittest.TestCase):
    """Preserve phase conversion, solved dates, lookup sampling, and reference."""

    def test_phase_conversion_and_temporal_reference(self) -> None:
        displacement = phase_to_los_displacement(
            np.array([0.0, 2.0 * np.pi]), 0.056, unit="mm"
        )
        np.testing.assert_allclose(displacement, [0.0, -28.0])

        values = np.array([[4.0, 8.0], [1.0, 2.0], [7.0, 14.0]])
        referenced, date = apply_temporal_reference(
            values,
            ["20240113", "20240101", "20240125"],
            mode="first",
        )
        self.assertEqual(date, "20240101")
        np.testing.assert_array_equal(referenced[1], [0.0, 0.0])

    def test_discovery_and_target_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "RESULT_mb_test"
            tpf_dir = root / "TS_TPF_DIFF"
            tpf_dir.mkdir(parents=True)
            (root / "20240101.dem.cropped.par").write_text(
                "width: 2\nnlines: 2\ncorner_lat: 1\ncorner_lon: 0\n"
                "post_lat: -1\npost_lon: 1\nEPSG: 4326\n",
                encoding="utf-8",
            )
            (root / "20240101.mli.par").write_text(
                "range_samples: 2\nazimuth_lines: 2\n"
                "radar_frequency: 5.4050005e+09 Hz\n",
                encoding="utf-8",
            )
            rows, columns = np.indices((2, 2))
            lookup = columns.astype(np.float32) + 1j * rows.astype(np.float32)
            np.asarray(lookup, dtype=">c8").tofile(
                root / "20240101.lookup_table_final"
            )
            np.ones((2, 2), dtype=np.uint8).tofile(root / "final.mask.bin")
            (root / "RMLI_tab").write_text(
                "/data/20240101.mli /data/20240101.mli.par\n"
                "/data/20240107.mli /data/20240107.mli.par\n"
                "/data/20240113.mli /data/20240113.mli.par\n",
                encoding="utf-8",
            )
            (root / "baseline_scelect_test").write_text(
                "20240101 20240113 10.0 12.0\n", encoding="utf-8"
            )
            np.zeros((2, 2), dtype=">f4").tofile(tpf_dir / "TS_tpf_001.tpf")
            np.full((2, 2), 2.0 * np.pi, dtype=">f4").tofile(
                tpf_dir / "TS_tpf_002.tpf"
            )

            with self.assertWarnsRegex(UserWarning, "excluded"):
                result = discover_gamma_mb_result(root)
            series = extract_target_timeseries(
                result,
                {"P1": (-0.5, 1.5, -0.5, 1.5)},
                unit="mm",
                temporal_reference="first",
            )

            expected = -result.wavelength_m * 500.0
            self.assertEqual(series.dates, ("20240101", "20240113"))
            self.assertEqual(series.reference_date, "20240101")
            self.assertEqual(series.pixel_counts["P1"], 4)
            np.testing.assert_allclose(series.values["P1"], [0.0, expected])


class TableTimeSeriesTests(unittest.TestCase):
    """Preserve target-table formats, GNSS ENU roles, projection, and alignment."""

    def test_target_csv_atomic_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "targets.csv"
            series = TargetTimeSeries(
                dates=("20240101", "20240113"),
                values={"P1": np.array([0.0, 1.5]), "P2": np.array([0.0, -2.0])},
                pixel_counts={"P1": 4, "P2": 3},
                unit="cm",
                reference_date="20240101",
            )

            write_target_timeseries_csv(series, path)
            loaded = read_target_timeseries_csv(path, unit="cm")

            self.assertEqual(loaded.dates, series.dates)
            np.testing.assert_array_equal(loaded.values["P1"], [0.0, 1.5])
            np.testing.assert_array_equal(loaded.values["P2"], [0.0, -2.0])
            self.assertEqual(list(path.parent.glob(".targets.*")), [])

    def test_legacy_wide_target_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "legacy.csv"
            path.write_text(
                "target,lon,lat,d20240101,d20240113\n"
                "P1,-16.7,28.2,0,1.5\n"
                "P2,-16.6,28.3,0,-2.0\n",
                encoding="utf-8",
            )
            series = read_target_timeseries_csv(path, unit="cm")
            self.assertEqual(series.dates, ("20240101", "20240113"))
            np.testing.assert_array_equal(series.values["P1"], [0.0, 1.5])
            np.testing.assert_array_equal(series.values["P2"], [0.0, -2.0])

    def test_gnss_daily_average_preserves_explicit_enu_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "gnss.csv"
            path.write_text(
                "time,N,E,U\n"
                "2024-01-01 00:00,10,1,100\n"
                "2024-01-01 12:00,14,3,104\n"
                "2024-01-02 00:00,16,4,106\n",
                encoding="utf-8",
            )
            series = read_gnss_timeseries(
                path,
                date_column="time",
                east_column="E",
                north_column="N",
                up_column="U",
                temporal_reference="first",
            )
            self.assertEqual(series.dates, ("20240101", "20240102"))
            np.testing.assert_array_equal(series.east, [0.0, 2.0])
            np.testing.assert_array_equal(series.north, [0.0, 4.0])
            np.testing.assert_array_equal(series.up, [0.0, 4.0])

    def test_enu_projection_and_common_date_alignment(self) -> None:
        los = project_enu_to_los(
            east=np.array([2.0]),
            north=np.array([4.0]),
            up=np.array([6.0]),
            incidence_deg=30.0,
            heading_deg=0.0,
        )
        np.testing.assert_allclose(los, [-1.0 + 3.0 * np.sqrt(3.0)])

        alignment = align_series_on_common_dates(
            ["20240101", "20240113", "20240125"],
            [0.0, 2.0, 4.0],
            ["20240113", "20240125", "20240206"],
            [10.0, 12.0, 14.0],
            method="first_common",
        )
        self.assertEqual(alignment.common_dates, ("20240113", "20240125"))
        self.assertAlmostEqual(alignment.offset, -8.0)
        self.assertAlmostEqual(alignment.rmse, 0.0)
        np.testing.assert_array_equal(alignment.candidate_values, [2.0, 4.0, 6.0])


if __name__ == "__main__":
    unittest.main()
