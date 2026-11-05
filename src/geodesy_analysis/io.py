"""Analysis output publication helpers.

功能概述:
    为 Analysis 最终文件提供同目录唯一临时路径与原子替换，失败时保留旧目标。

函数说明:
    ``atomic_output_path`` 创建私有临时文件，调用体成功后替换目标，异常时仅删除
    本次调用创建的临时文件。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator


@contextmanager
def atomic_output_path(path: str | Path) -> Iterator[Path]:
    """Yield a sibling temporary path and replace the destination on success."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=destination.suffix or ".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_output_directory(destination: Path) -> Iterator[Path]:
    """Yield staging and publish only when the destination is absent."""

    output = Path(destination)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".stage", dir=output.parent)
    )
    try:
        yield staging
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"output directory appeared during run: {output}")
        os.replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


@contextmanager
def atomic_replace_output_directory(
    destination: Path,
) -> Generator[Path, None, None]:
    """Stage a directory and replace the destination only after success."""

    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.", suffix=".stage", dir=output.parent
        )
    )
    backup_root: Path | None = None
    previous = False
    try:
        yield staging
        if output.exists() or output.is_symlink():
            backup_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{output.name}.", suffix=".backup", dir=output.parent
                )
            )
            os.replace(output, backup_root / "previous")
            previous = True
        try:
            os.replace(staging, output)
        except BaseException:
            if previous:
                os.replace(backup_root / "previous", output)
                previous = False
            raise
        if backup_root is not None:
            shutil.rmtree(backup_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if backup_root is not None and backup_root.exists():
            if previous and not (output.exists() or output.is_symlink()):
                os.replace(backup_root / "previous", output)
            if backup_root.exists():
                shutil.rmtree(backup_root, ignore_errors=True)
        raise


@contextmanager
def atomic_replace_output_directories(
    *destinations: Path,
) -> Generator[tuple[Path, ...], None, None]:
    """Stage several directories and replace their destinations as one unit."""

    outputs = tuple(Path(destination) for destination in destinations)
    if len(outputs) < 2:
        raise ValueError("at least two output directories are required")
    if len({output.resolve() for output in outputs}) != len(outputs):
        raise ValueError("output directories must be distinct")

    staging: list[Path] = []
    backups: list[Path | None] = [None] * len(outputs)
    published: list[tuple[Path, int]] = []
    try:
        for output in outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
            staging.append(
                Path(
                    tempfile.mkdtemp(
                        prefix=f".{output.name}.",
                        suffix=".stage",
                        dir=output.parent,
                    )
                )
            )
        yield tuple(staging)

        for index, output in enumerate(outputs):
            if output.exists() or output.is_symlink():
                backup = Path(
                    tempfile.mkdtemp(
                        prefix=f".{output.name}.",
                        suffix=".backup",
                        dir=output.parent,
                    )
                )
                backups[index] = backup
                os.replace(output, backup / "previous")

        for temporary, output in zip(staging, outputs):
            inode = temporary.stat(follow_symlinks=False).st_ino
            os.replace(temporary, output)
            published.append((output, inode))
    except BaseException:
        for output, inode in reversed(published):
            try:
                if output.stat(follow_symlinks=False).st_ino == inode:
                    if output.is_dir() and not output.is_symlink():
                        shutil.rmtree(output)
                    else:
                        output.unlink()
            except FileNotFoundError:
                pass
        for output, backup in reversed(tuple(zip(outputs, backups))):
            previous = backup / "previous" if backup is not None else None
            if previous is not None and (previous.exists() or previous.is_symlink()):
                os.replace(backup / "previous", output)
        for temporary in staging:
            shutil.rmtree(temporary, ignore_errors=True)
        for backup in backups:
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
        raise
    else:
        for backup in backups:
            if backup is not None:
                shutil.rmtree(backup)


@contextmanager
def atomic_output_directories(
    *destinations: Path,
) -> Iterator[tuple[Path, ...]]:
    """Stage several directories and publish only when every target is absent."""

    outputs = tuple(Path(destination) for destination in destinations)
    if len(outputs) < 2:
        raise ValueError("at least two output directories are required")
    if len({output.resolve() for output in outputs}) != len(outputs):
        raise ValueError("output directories must be distinct")
    existing = [output for output in outputs if output.exists() or output.is_symlink()]
    if existing:
        raise FileExistsError(
            "output directories already exist: "
            + ", ".join(str(output) for output in existing)
        )

    staging: list[Path] = []
    published: list[tuple[Path, int]] = []
    try:
        for output in outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
            staging.append(
                Path(
                    tempfile.mkdtemp(
                        prefix=f".{output.name}.",
                        suffix=".stage",
                        dir=output.parent,
                    )
                )
            )
        yield tuple(staging)
        appeared = [
            output for output in outputs if output.exists() or output.is_symlink()
        ]
        if appeared:
            raise FileExistsError(
                "output directories appeared during run: "
                + ", ".join(str(output) for output in appeared)
            )
        for temporary, output in zip(staging, outputs):
            inode = temporary.stat(follow_symlinks=False).st_ino
            os.replace(temporary, output)
            published.append((output, inode))
    except BaseException:
        for output, inode in reversed(published):
            try:
                if output.stat(follow_symlinks=False).st_ino == inode:
                    shutil.rmtree(output)
            except FileNotFoundError:
                pass
        for temporary in staging:
            shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = [
    "atomic_output_directories",
    "atomic_output_directory",
    "atomic_replace_output_directory",
    "atomic_replace_output_directories",
    "atomic_output_path",
]
