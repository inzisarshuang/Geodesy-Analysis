"""Tests for the strict PRE registered-stack input contract."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.common.registered_stack import read_registered_stack


class RegisteredStackTests(unittest.TestCase):
    """Reject ambiguous stacks before a scientific command can start."""

    def _write_stack(self, root: Path, **changes: object) -> Path:
        stack_dir = root / "PRE" / "RSLC"
        data_dir = stack_dir / "RSLC"
        data_dir.mkdir(parents=True)
        for date in ("20231214", "20231226"):
            (data_dir / f"{date}.rslc").write_bytes(b"complex")
            (data_dir / f"{date}.rslc.par").write_text(
                "range_samples: 2\nazimuth_lines: 1\n", encoding="utf-8"
            )
        payload: dict[str, object] = {
            "schema_version": 2,
            "status": "complete",
            "sensor": "sentinel1",
            "backend": {"name": "gamma", "version": "2023"},
            "geometry_type": "radar_grid",
            "reference_date": "20231226",
            "dates": ["20231214", "20231226"],
            "polarizations": ["VV"],
            "assets": [
                {
                    "date": date,
                    "polarization": "VV",
                    "data_path": f"RSLC/{date}.rslc",
                    "parameter_path": f"RSLC/{date}.rslc.par",
                }
                for date in ("20231214", "20231226")
            ],
        }
        payload.update(changes)
        manifest = stack_dir / "registered_stack.json"
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    def test_reads_complete_requested_polarization_and_preserves_date_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_stack(root)
            stack = read_registered_stack(
                manifest, project_root=root, polarization="vv"
            )
            self.assertEqual(stack.sensor, "sentinel1")
            self.assertEqual(stack.reference_date, "20231226")
            self.assertEqual(stack.dates, ("20231214", "20231226"))
            self.assertEqual(stack.polarizations, ("VV",))
            self.assertEqual([asset.date for asset in stack.assets], list(stack.dates))
            self.assertTrue(all(asset.polarization == "VV" for asset in stack.assets))
            self.assertTrue(all(asset.data_path.is_absolute() for asset in stack.assets))
            self.assertEqual(
                stack.source_digest,
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )

    def test_rejects_status_backend_geometry_and_duplicate_dates(self) -> None:
        mutations = (
            ({"status": "failed"}, "status must be complete"),
            ({"backend": {"name": "isce3"}}, "backend must be gamma"),
            ({"geometry_type": "map_grid"}, "geometry_type must be radar_grid"),
            (
                {"dates": ["20231214", "20231214"]},
                "dates must be unique",
            ),
        )
        for changes, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self._write_stack(root, **changes)
                with self.assertRaisesRegex(ValueError, message):
                    read_registered_stack(
                        manifest, project_root=root, polarization="VV"
                    )

    def test_rejects_missing_polarization_or_incomplete_date_grid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_stack(root)
            with self.assertRaisesRegex(ValueError, "polarization HH"):
                read_registered_stack(manifest, project_root=root, polarization="HH")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_stack(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["assets"] = payload["assets"][:1]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing asset.*20231226.*VV"):
                read_registered_stack(manifest, project_root=root, polarization="VV")

    def test_rejects_asset_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_stack(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["assets"][0]["data_path"] = "../escape.rslc"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "asset data path"):
                read_registered_stack(manifest, project_root=root, polarization="VV")

    def test_rejects_missing_or_empty_asset_files(self) -> None:
        for target, expected in (
            ("20231214.rslc", "missing asset data"),
            ("20231214.rslc.par", "empty asset parameter"),
        ):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self._write_stack(root)
                path = manifest.parent / "RSLC" / target
                if target.endswith(".par"):
                    path.write_bytes(b"")
                else:
                    path.unlink()
                with self.assertRaisesRegex((FileNotFoundError, ValueError), expected):
                    read_registered_stack(
                        manifest, project_root=root, polarization="VV"
                    )


if __name__ == "__main__":
    unittest.main()
