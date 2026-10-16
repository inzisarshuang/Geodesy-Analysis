"""Exact contracts for stage-owned GAMMA DISP quicklooks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.insar.common.gamma_quicklooks import (
    coherence_quicklook_command,
    mli_quicklook_command,
    require_nonempty_quicklook,
    unwrapped_phase_quicklook_command,
    wrapped_phase_quicklook_command,
)


class GammaQuicklookTests(unittest.TestCase):
    def test_mli_command_uses_legacy_gray_display_arguments(self) -> None:
        self.assertEqual(
            mli_quicklook_command(Path("scene.mli"), 137, Path("scene.mli.bmp")),
            (
                "raspwr",
                "scene.mli",
                "137",
                "1",
                "0",
                "1",
                "1",
                "1.",
                ".35",
                "gray.cm",
                "scene.mli.bmp",
            ),
        )

    def test_wrapped_commands_preserve_interferogram_filter_and_nl_modes(self) -> None:
        self.assertEqual(
            wrapped_phase_quicklook_command(
                Path("pair.tflt"), 137, Path("pair.tflt.bmp")
            ),
            (
                "rasmph",
                "pair.tflt",
                "137",
                "1",
                "-",
                "1",
                "1",
                "1",
                ".35",
                "rmg.cm",
                "pair.tflt.bmp",
            ),
        )
        self.assertEqual(
            wrapped_phase_quicklook_command(
                Path("pair.tflt.filt"),
                137,
                Path("pair.tflt.filt.bmp"),
                line_start="0",
            )[4],
            "0",
        )
        self.assertEqual(
            wrapped_phase_quicklook_command(
                Path("pair.tflt.filt"),
                137,
                Path("pair.tflt.filt.bmp"),
                nonlocal_mode=True,
            ),
            (
                "rasdt_pwr",
                "pair.tflt.filt",
                "-",
                "137",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "2",
                "rmg.cm",
                "pair.tflt.filt.bmp",
            ),
        )

    def test_coherence_commands_select_background_contract(self) -> None:
        self.assertEqual(
            coherence_quicklook_command(
                Path("pair.coh.filt"),
                137,
                Path("pair.coh.filt.bmp"),
                background=Path("ave_mli"),
            ),
            (
                "rasdt_pwr",
                "pair.coh.filt",
                "ave_mli",
                "137",
                "-",
                "-",
                "-",
                "-",
                "0",
                "1",
                "0",
                "cc.cm",
                "pair.coh.filt.bmp",
            ),
        )
        self.assertEqual(
            coherence_quicklook_command(
                Path("pair.cc"), 137, Path("pair.cc.bmp"), background=None
            )[1:],
            (
                "pair.cc",
                "-",
                "137",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "2",
                "cc.cm",
                "pair.cc.bmp",
            ),
        )

    def test_unwrapped_command_uses_rmg_color_map(self) -> None:
        self.assertEqual(
            unwrapped_phase_quicklook_command(
                Path("pair.tflt.filt.unw"), 137, Path("pair.tflt.filt.unw.bmp")
            ),
            (
                "rasdt_pwr",
                "pair.tflt.filt.unw",
                "-",
                "137",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "2",
                "rmg.cm",
                "pair.tflt.filt.unw.bmp",
            ),
        )

    def test_validation_rejects_missing_and_empty_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.bmp"
            with self.assertRaisesRegex(RuntimeError, "phase.*missing"):
                require_nonempty_quicklook(missing, "phase")
            empty = root / "empty.bmp"
            empty.touch()
            with self.assertRaisesRegex(RuntimeError, "phase.*empty"):
                require_nonempty_quicklook(empty, "phase")
            complete = root / "complete.bmp"
            complete.write_bytes(b"BM")
            self.assertEqual(require_nonempty_quicklook(complete, "phase"), complete)


if __name__ == "__main__":
    unittest.main()
