"""Manifest-only filtering planning tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.filtering.config import load_filtering_config
from geodesy_analysis.insar.filtering.plan import build_filtering_plan
from geodesy_analysis.insar.filtering.publication import filtering_input_signature


class FilteringPlanTests(unittest.TestCase):
    dates = ("20231226", "20240131", "20240212")

    def _project(self, root: Path, *, schema: int = 1, status: str = "complete") -> tuple[Path, Path]:
        output = root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
        output.mkdir(parents=True)
        mli_assets = []
        for date in self.dates:
            data = output / "MLI" / f"{date}.mli"
            parameter = output / "MLI" / f"{date}.mli.par"
            data.parent.mkdir(exist_ok=True)
            data.write_bytes(b"m" * 24)
            parameter.write_text("range_samples: 3\nazimuth_lines: 2\n", encoding="utf-8")
            mli_assets.append(
                {"date": date, "data_path": f"MLI/{date}.mli", "parameter_path": f"MLI/{date}.mli.par"}
            )
        pairs = []
        for name in ("20240131-20240212", "20231226-20240131"):
            pair = output / "PAIRS" / name / "pair.tflt"
            pair.parent.mkdir(parents=True)
            pair.write_bytes(b"c" * 48)
            pairs.append({"pair": name, "products": {"differential_interferogram": f"PAIRS/{name}/pair.tflt"}})
        manifest = output / "interferogram_manifest.json"
        payload = {
            "schema_version": schema,
            "status": status,
            "case_id": "S1/ASCENDING_128",
            "mli_assets": mli_assets,
            "pairs": pairs,
        }
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        config = root / "config/analysis/insar_filtering.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"""[project]\nroot = {root}\n[case:main]\ncase_root = S1/ASCENDING_128\ninterferogram_manifest = S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json\nmethod = gamma_bm3d\n""",
            encoding="utf-8",
        )
        return manifest, config

    def test_resolves_and_sorts_manifest_assets_with_stable_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, config = self._project(root)
            (case,) = load_filtering_config(config)
            first = build_filtering_plan(case)
            second = build_filtering_plan(case)
            self.assertEqual((first.width, first.lines), (3, 2))
            self.assertEqual([pair.name for pair in first.pairs], ["20231226-20240131", "20240131-20240212"])
            self.assertEqual(first.pairs[0].master_mli, manifest.parent / "MLI/20231226.mli")
            self.assertEqual(first.pairs[0].slave_mli, manifest.parent / "MLI/20240131.mli")
            self.assertEqual(first.pairs[0].interferogram, manifest.parent / "PAIRS/20231226-20240131/pair.tflt")
            self.assertEqual(filtering_input_signature(first), filtering_input_signature(second))

    def test_accepts_schema_two_case_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, config = self._project(root, schema=2)
            (case,) = load_filtering_config(config)
            self.assertEqual(build_filtering_plan(case).manifest.schema_version, 2)

    def test_rejects_bad_manifest_or_missing_and_wrong_sized_products(self) -> None:
        mutations = (
            ("status", lambda payload, root: payload.update(status="running"), "status must be complete"),
            ("schema", lambda payload, root: payload.update(schema_version=9), "schema_version"),
            ("case", lambda payload, root: payload.update(case_id="S1/DESCENDING_135", schema_version=2), "case_id"),
            ("missing-tflt", lambda payload, root: (root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/PAIRS/20231226-20240131/pair.tflt").unlink(), "differential interferogram"),
            ("missing-mli", lambda payload, root: (root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/MLI/20231226.mli").unlink(), "MLI"),
            ("bad-size", lambda payload, root: (root / "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/PAIRS/20231226-20240131/pair.tflt").write_bytes(b"short"), "byte size"),
        )
        for name, mutate, message in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, config = self._project(root)
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                mutate(payload, root)
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                (case,) = load_filtering_config(config)
                with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                    build_filtering_plan(case)


if __name__ == "__main__":
    unittest.main()
