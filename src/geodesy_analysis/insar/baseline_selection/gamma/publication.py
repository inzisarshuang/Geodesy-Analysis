"""Baseline-record parsing, identity, and manifest publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import GammaBaselinePlan


@dataclass(frozen=True)
class BaselineRecord:
    """One normalized chronological interferometric pair."""

    master: str
    slave: str
    perpendicular: float
    temporal: float


def _date(value: str, line_number: int) -> str:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid date on Berp_SC line {line_number}: {value!r}")
    return value


def parse_berp_sc(path: Path) -> tuple[BaselineRecord, ...]:
    """Parse GAMMA Berp_SC, drop self-pairs, normalize order, and deduplicate."""

    source = Path(path)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"base_calc did not create a non-empty Berp_SC: {source}")
    records: dict[tuple[str, str], BaselineRecord] = {}
    for line_number, raw in enumerate(
        source.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        fields = raw.split()
        if not fields:
            continue
        if len(fields) < 5:
            raise ValueError(f"cannot parse Berp_SC line {line_number}: {raw}")
        first = _date(fields[1], line_number)
        second = _date(fields[2], line_number)
        try:
            perpendicular = float(fields[3])
            temporal = float(fields[4])
        except ValueError as error:
            raise ValueError(f"cannot parse Berp_SC line {line_number}: {raw}") from error
        if first == second:
            continue
        if first > second:
            master, slave = second, first
            perpendicular = -perpendicular
            temporal = -temporal
        else:
            master, slave = first, second
        record = BaselineRecord(master, slave, perpendicular, abs(temporal))
        key = (master, slave)
        previous = records.get(key)
        if previous is not None and previous != record:
            raise ValueError(f"conflicting Berp_SC rows for pair {master}-{slave}")
        records[key] = record
    if not records:
        raise ValueError(f"base_calc produced no interferometric pairs: {source}")
    return tuple(records[key] for key in sorted(records))


def baseline_input_signature(plan: GammaBaselinePlan) -> str:
    """Return a deterministic identity for every baseline-selection input."""

    payload = {
        "max_perpendicular_baseline": plan.case.max_perpendicular_baseline,
        "max_temporal_baseline": plan.case.max_temporal_baseline,
        "network_type": plan.case.network_type,
        "polarization": plan.case.polarization,
        "reference_date": plan.stack.reference_date,
        "stack_digest": plan.stack.source_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def write_network_files(
    directory: Path,
    network_type: str,
    records: tuple[BaselineRecord, ...],
) -> tuple[Path, Path]:
    """Write deterministic pair-name and four-column baseline tables."""

    image_pairs = directory / f"image_pairs_{network_type}"
    network = directory / f"baseline_select_{network_type}"
    image_pairs.write_text(
        "".join(f"{row.master}-{row.slave}\n" for row in records),
        encoding="utf-8",
    )
    network.write_text(
        "".join(
            f"{row.master} {row.slave} {_number(row.perpendicular)} "
            f"{_number(row.temporal)}\n"
            for row in records
        ),
        encoding="utf-8",
    )
    return image_pairs, network


__all__ = [
    "BaselineRecord",
    "baseline_input_signature",
    "parse_berp_sc",
    "write_network_files",
]
