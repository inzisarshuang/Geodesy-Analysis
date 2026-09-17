"""Analysis output publication helpers.

功能概述:
    为 Analysis 最终文件提供同目录唯一临时路径与原子替换，失败时保留旧目标。

函数说明:
    ``atomic_output_path`` 创建私有临时文件，调用体成功后替换目标，异常时仅删除
    本次调用创建的临时文件。
"""

from __future__ import annotations

import os
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
