"""Interferogram network manifest parsing.

功能概述:
    读取 GAMMA shortbaseline 或 baseline_select 清单中的主从影像日期，并保持
    来源顺序供 Analysis 网络和时序逻辑使用。

函数说明:
    ``read_interferogram_pairs`` 兼容连字符单列和主从双列格式，返回标准化的
    ``YYYYMMDD-YYYYMMDD`` 字符串列表。
"""

from __future__ import annotations

from pathlib import Path


def read_interferogram_pairs(path: str | Path) -> list[str]:
    """Read valid acquisition pairs from one required network manifest."""

    source = Path(path)
    pairs: list[str] = []
    for raw_line in source.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        first = parts[0]
        if len(first) == 17 and first[8] == "-":
            master, slave = first[:8], first[9:17]
        elif len(parts) >= 2:
            master, slave = parts[0], parts[1]
        else:
            continue
        if (
            len(master) == 8
            and master.isdigit()
            and len(slave) == 8
            and slave.isdigit()
        ):
            pairs.append(f"{master}-{slave}")
    return pairs
