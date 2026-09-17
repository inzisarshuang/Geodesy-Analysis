"""Tests for Analysis-local atomic output publication."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.io import atomic_output_path


class AtomicOutputTests(unittest.TestCase):
    """Verify success replacement and interruption safety."""

    def test_success_atomically_replaces_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "series.csv"
            destination.write_text("old", encoding="utf-8")

            with atomic_output_path(destination) as temporary:
                self.assertEqual(temporary.parent, destination.parent)
                self.assertNotEqual(temporary, destination)
                temporary.write_text("new", encoding="utf-8")

            self.assertEqual(destination.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(destination.parent.glob(".series.*")), [])

    def test_failure_preserves_destination_and_removes_private_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "series.csv"
            destination.write_text("old", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "stop"):
                with atomic_output_path(destination) as temporary:
                    temporary.write_text("partial", encoding="utf-8")
                    raise RuntimeError("stop")

            self.assertEqual(destination.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(destination.parent.glob(".series.*")), [])


if __name__ == "__main__":
    unittest.main()
