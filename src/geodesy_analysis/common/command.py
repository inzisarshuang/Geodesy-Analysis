"""Shell-free subprocess execution with explicit Analysis log files."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    """Completed command identity and its persistent logs."""

    command: tuple[str, ...]
    returncode: int
    stdout_log: Path
    stderr_log: Path


class CommandExecutionError(RuntimeError):
    """A command returned a non-zero status; detailed output remains on disk."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.stderr_log = result.stderr_log
        super().__init__(
            f"command failed with exit code {result.returncode}; "
            f"inspect {result.stderr_log}"
        )


class SubprocessCommandRunner:
    """Execute one argv sequence directly, without invoking a shell."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        stdin_text: str | None,
        stdout_path: Path,
        stderr_path: Path,
    ) -> CommandResult:
        normalized = tuple(str(value) for value in command)
        if not normalized:
            raise ValueError("command must not be empty")
        working_directory = Path(cwd).resolve(strict=True)
        stdout_log = Path(stdout_path)
        stderr_log = Path(stderr_path)
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        with stdout_log.open("w", encoding="utf-8") as stdout, stderr_log.open(
            "w", encoding="utf-8"
        ) as stderr:
            completed = subprocess.run(
                normalized,
                cwd=working_directory,
                input=stdin_text,
                text=True,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
        result = CommandResult(
            normalized, completed.returncode, stdout_log, stderr_log
        )
        if result.returncode != 0:
            raise CommandExecutionError(result)
        return result


__all__ = ["CommandExecutionError", "CommandResult", "SubprocessCommandRunner"]
