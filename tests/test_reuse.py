"""Tests for Analysis completion-aware science reuse."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output


class AnalysisReuseTests(unittest.TestCase):
    def test_states_cover_absent_complete_incomplete_corrupt_mismatch_and_missing_figures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "FILTERING/NL_INSAR"
            absent = classify_analysis_output(output, "manifest.json", "sig")
            self.assertEqual(absent.state, ReuseState.ABSENT)

            output.mkdir(parents=True)
            product = output / "pair.filt"
            product.write_bytes(b"science")
            figure = root / "FIGURES/FILTERING/NL_INSAR/pair.bmp"
            manifest = output / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "input_signature": "sig",
                        "required_products": ["pair.filt"],
                        "figures": [str(figure)],
                    }
                ),
                encoding="utf-8",
            )
            missing_figure = classify_analysis_output(output, "manifest.json", "sig")
            self.assertEqual(missing_figure.state, ReuseState.FIGURES_MISSING)
            self.assertTrue(missing_figure.science_reusable)

            figure.parent.mkdir(parents=True)
            figure.write_bytes(b"image")
            complete = classify_analysis_output(output, "manifest.json", "sig")
            self.assertEqual(complete.state, ReuseState.COMPLETE)

            product.unlink()
            self.assertEqual(
                classify_analysis_output(output, "manifest.json", "sig").state,
                ReuseState.INCOMPLETE,
            )
            product.write_bytes(b"science")
            self.assertEqual(
                classify_analysis_output(output, "manifest.json", "changed").state,
                ReuseState.MISMATCH,
            )
            manifest.write_text("not-json", encoding="utf-8")
            self.assertEqual(
                classify_analysis_output(output, "manifest.json", "sig").state,
                ReuseState.CORRUPT,
            )


if __name__ == "__main__":
    unittest.main()
