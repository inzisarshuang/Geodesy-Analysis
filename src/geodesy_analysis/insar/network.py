"""Interferogram network manifest parsing.

功能概述:
    读取 GAMMA shortbaseline 或 baseline_select 清单中的主从影像日期，并保持
    来源顺序供 Analysis 网络和时序逻辑使用。

函数说明:
    ``read_interferogram_pairs`` 兼容连字符单列和主从双列格式，返回标准化的
    ``YYYYMMDD-YYYYMMDD`` 字符串列表。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class GammaNetworkRecord:
    """One strict GAMMA baseline-network row."""

    master: str
    slave: str
    perpendicular_baseline: float
    temporal_baseline_days: float

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


def _date(value: str, label: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}") from error
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}")
    return value


def read_gamma_network_records(path: str | Path) -> tuple[GammaNetworkRecord, ...]:
    """Read strict four-column GAMMA baseline records in source order."""

    source = Path(path)
    records: list[GammaNetworkRecord] = []
    names: set[str] = set()
    for line_number, raw_line in enumerate(
        source.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(
                f"GAMMA network row must contain four columns at "
                f"{source}:{line_number}"
            )
        master = _date(fields[0], "master date")
        slave = _date(fields[1], "slave date")
        try:
            perpendicular = float(fields[2])
            temporal = float(fields[3])
        except ValueError as error:
            raise ValueError(
                f"GAMMA network baselines must be numbers at {source}:{line_number}"
            ) from error
        if not math.isfinite(perpendicular) or not math.isfinite(temporal):
            raise ValueError(
                f"GAMMA network baselines must be finite at {source}:{line_number}"
            )
        record = GammaNetworkRecord(master, slave, perpendicular, temporal)
        if record.name in names:
            raise ValueError(f"duplicate GAMMA network pair: {record.name}")
        names.add(record.name)
        records.append(record)
    if not records:
        raise ValueError(f"GAMMA network contains no records: {source}")
    return tuple(records)


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


__all__ = [
    "GammaNetworkRecord",
    "read_gamma_network_records",
    "read_interferogram_pairs",
]
