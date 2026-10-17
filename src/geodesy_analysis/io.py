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
from typing import Iterator


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
    """Yield a sibling staging directory and publish it only on success."""

    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output directory already exists: {output}")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.", suffix=".stage", dir=output.parent
        )
    )
    try:
        yield staging
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"output directory already exists: {output}")
        os.replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


@contextmanager
def atomic_output_directories(
    *destinations: Path,
) -> Iterator[tuple[Path, ...]]:
    """Stage several directories and publish them as one recoverable unit."""

    outputs = tuple(Path(destination) for destination in destinations)
    if len(outputs) < 2:
        raise ValueError("at least two output directories are required")
    if len({output.resolve() for output in outputs}) != len(outputs):
        raise ValueError("output directories must be distinct")
    staging: list[Path] = []
    published: list[tuple[Path, int]] = []
    try:
        for output in outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists() or output.is_symlink():
                raise FileExistsError(f"output directory already exists: {output}")
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
        for output in outputs:
            if output.exists() or output.is_symlink():
                raise FileExistsError(f"output directory already exists: {output}")
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
    "atomic_output_path",
]
