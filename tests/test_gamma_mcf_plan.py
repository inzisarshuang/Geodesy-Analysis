"""Filtering-manifest planning tests for GAMMA MCF."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.unwrapping.gamma.mcf.config import load_gamma_mcf_config
from geodesy_analysis.insar.unwrapping.gamma.mcf.plan import build_gamma_mcf_plan
from geodesy_analysis.insar.unwrapping.gamma.mcf.publication import unwrapping_input_signature


class GammaMcfPlanTests(unittest.TestCase):
    def _project(self, root: Path) -> tuple[Path, Path, Path]:
        case = root / "S1/ASCENDING_128"
        upstream = case / "ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
        dates = ("20231226", "20240131", "20240212")
        mli = []
        for date in dates:
            data = upstream / "MLI" / f"{date}.mli"
            par = upstream / "MLI" / f"{date}.mli.par"
            data.parent.mkdir(parents=True, exist_ok=True)
            np.ones((2, 3), dtype=">f4").tofile(data)
            par.write_text("range_samples: 3\nazimuth_lines: 2\n", encoding="utf-8")
            mli.append({"date": date, "data_path": f"MLI/{date}.mli", "parameter_path": f"MLI/{date}.mli.par"})
        hgt = case / "PRE/GAMMA/GEOMETRY/reference.hgt_sim"
        hgt.parent.mkdir(parents=True)
        np.ones((2, 3), dtype=">f4").tofile(hgt)
        pair_names = ("20240131-20240212", "20231226-20240131")
        upstream_manifest = upstream / "interferogram_manifest.json"
        upstream_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "case_id": "S1/ASCENDING_128",
                    "mli_assets": mli,
                    "pairs": [{"pair": name, "products": {"differential_interferogram": f"PAIRS/{name}/pair.tflt"}} for name in pair_names],
                    "radar_height_project_path": "S1/ASCENDING_128/PRE/GAMMA/GEOMETRY/reference.hgt_sim",
                }
            ),
            encoding="utf-8",
        )
        filtering = case / "ANALYSIS/FILTERING/NL_INSAR"
        filtering.mkdir(parents=True)
        pairs = []
        for name in pair_names:
            directory = filtering / "pairs" / name
            directory.mkdir(parents=True)
            np.ones((2, 3), dtype=">c8").tofile(directory / "pair.tflt.filt")
            np.full((2, 3), 0.7, dtype=">f4").tofile(directory / "pair.coh.filt")
            pairs.append({"pair": name, "products": {"filtered_interferogram": f"pairs/{name}/pair.tflt.filt", "filtered_coherence": f"pairs/{name}/pair.coh.filt"}})
        np.full((2, 3), 0.7, dtype=">f4").tofile(filtering / "coh_ave.coh")
        filtering_manifest = filtering / "filtering_manifest.json"
        filtering_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "complete",
                    "case_id": "S1/ASCENDING_128",
                    "method": "nl_insar",
                    "grid": {"width": 3, "lines": 2},
                    "interferogram_manifest_project_path": "S1/ASCENDING_128/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA/interferogram_manifest.json",
                    "interferogram_manifest_digest": hashlib.sha256(upstream_manifest.read_bytes()).hexdigest(),
                    "mean_coherence_path": "coh_ave.coh",
                    "pair_count": 2,
                    "pairs": pairs,
                }
            ),
            encoding="utf-8",
        )
        config = root / "config/analysis/gamma_mcf_unwrapping.cfg"
        config.parent.mkdir(parents=True)
        config.write_text(
            f"[project]\nroot = {root}\n[case:main]\ncase_root = S1/ASCENDING_128\nfiltering_manifest = S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR/filtering_manifest.json\n",
            encoding="utf-8",
        )
        return filtering_manifest, upstream_manifest, config

    def test_resolves_pairs_upstream_assets_and_stable_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filtering, upstream, config = self._project(root)
            plan = build_gamma_mcf_plan(load_gamma_mcf_config(config)[0])
            self.assertEqual((plan.width, plan.lines), (3, 2))
            self.assertEqual(plan.filtering.method, "nl_insar")
            self.assertEqual(plan.filtering.interferogram_manifest, upstream)
            self.assertEqual([pair.name for pair in plan.pairs], ["20231226-20240131", "20240131-20240212"])
            self.assertEqual(plan.mean_coherence, filtering.parent / "coh_ave.coh")
            self.assertEqual(len(plan.mli_assets), 3)
            self.assertTrue(plan.radar_height.name.endswith("hgt_sim"))
            self.assertEqual(unwrapping_input_signature(plan), unwrapping_input_signature(plan))

    def test_rejects_malformed_missing_wrong_size_and_upstream_mismatch(self) -> None:
        mutations = (
            ("schema", lambda f, u, p: f.update(schema_version=1), "schema_version"),
            ("status", lambda f, u, p: f.update(status="running"), "status must be complete"),
            ("missing-product", lambda f, u, p: (p / "S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR/pairs/20231226-20240131/pair.coh.filt").unlink(), "filtered coherence"),
            ("wrong-size", lambda f, u, p: (p / "S1/ASCENDING_128/ANALYSIS/FILTERING/NL_INSAR/coh_ave.coh").write_bytes(b"bad"), "byte size"),
            ("digest", lambda f, u, p: f.update(interferogram_manifest_digest="bad"), "digest"),
            ("pairs", lambda f, u, p: u.update(pairs=u["pairs"][:1]), "pair inventory"),
        )
        for name, mutate, message in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                filtering, upstream, config = self._project(root)
                f_payload = json.loads(filtering.read_text(encoding="utf-8"))
                u_payload = json.loads(upstream.read_text(encoding="utf-8"))
                mutate(f_payload, u_payload, root)
                upstream_bytes = json.dumps(u_payload).encode()
                if name == "pairs":
                    f_payload["interferogram_manifest_digest"] = hashlib.sha256(
                        upstream_bytes
                    ).hexdigest()
                filtering.write_text(json.dumps(f_payload), encoding="utf-8")
                upstream.write_bytes(upstream_bytes)
                with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                    build_gamma_mcf_plan(load_gamma_mcf_config(config)[0])


if __name__ == "__main__":
    unittest.main()
