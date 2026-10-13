"""Tests for shared Analysis workflow infrastructure."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from geodesy_analysis.common.command import (
    CommandExecutionError,
    SubprocessCommandRunner,
)
from geodesy_analysis.common.paths import validate_within_root
from geodesy_analysis.common.progress import ConsoleProgress, PROGRESS_PREFIX, emit_progress
from geodesy_analysis.io import atomic_output_directory


class WorkflowCommonTests(unittest.TestCase):
    """Pin project confinement, progress, commands, and publication."""

    def test_paths_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            inside = root / "ANALYSIS" / "result"
            self.assertEqual(
                validate_within_root(inside, root, "output"), inside.resolve()
            )
            with self.assertRaisesRegex(ValueError, "output.*project root"):
                validate_within_root(root.parent / "outside", root, "output")

    def test_progress_matches_pre_protocol(self) -> None:
        line = emit_progress(
            event="item_started",
            task="ANALYSIS_TEST",
            timestamp="2026-10-13T00:00:00Z",
            item="20231214-20231226",
            index=1,
            total=2,
            stage="base_calc",
            status="start",
        )
        self.assertTrue(line.startswith(PROGRESS_PREFIX))
        rendered: list[str] = []
        ConsoleProgress(writer=rendered.append)(line)
        self.assertEqual(
            rendered,
            [
                "[ANALYSIS_TEST] [1/2 50.0%] "
                "item=20231214-20231226 stage=base_calc status=start"
            ],
        )

    def test_command_failure_names_stderr_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            runner = SubprocessCommandRunner()
            with self.assertRaises(CommandExecutionError) as caught:
                runner.run(
                    (
                        sys.executable,
                        "-c",
                        "import sys; print('out'); print('bad', file=sys.stderr); sys.exit(7)",
                    ),
                    cwd=root,
                    stdin_text=None,
                    stdout_path=stdout,
                    stderr_path=stderr,
                )
            self.assertEqual(caught.exception.result.returncode, 7)
            self.assertEqual(caught.exception.stderr_log, stderr)
            self.assertEqual(stdout.read_text(encoding="utf-8"), "out\n")
            self.assertEqual(stderr.read_text(encoding="utf-8"), "bad\n")

    def test_atomic_directory_publishes_only_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "BASELINE"
            with atomic_output_directory(destination) as staging:
                self.assertEqual(staging.parent, destination.parent)
                (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
            self.assertTrue((destination / "manifest.json").is_file())

            failed = root / "INTERFEROGRAM"
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with atomic_output_directory(failed) as staging:
                    (staging / "partial").write_text("x", encoding="utf-8")
                    raise RuntimeError("stop")
            self.assertFalse(failed.exists())

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                with atomic_output_directory(destination):
                    pass


if __name__ == "__main__":
    unittest.main()
