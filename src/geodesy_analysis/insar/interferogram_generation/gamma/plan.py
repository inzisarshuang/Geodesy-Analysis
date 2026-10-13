"""Cross-stage validation and side-effect-free interferogram planning."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from geodesy_analysis.common.paths import validate_within_root
from geodesy_analysis.insar.common.registered_stack import read_registered_stack

from .models import (
    BaselineManifest,
    GammaInterferogramCase,
    GammaInterferogramPlan,
    InterferogramPair,
)


def _date(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}") from error
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}")
    return value


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"baseline manifest {key} is required")
    return value.strip()


def read_baseline_manifest(
    path: Path, *, project_root: Path
) -> BaselineManifest:
    """Read baseline identity without opening its network table.

    Delaying network I/O lets the planner reject an accidental cross-stage
    stack mismatch before it inspects any derived products.
    """

    root = Path(project_root).expanduser().resolve(strict=True)
    source = validate_within_root(Path(path), root, "baseline manifest")
    if not source.is_file():
        raise FileNotFoundError(f"baseline manifest not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid baseline manifest JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("baseline manifest root must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("baseline manifest schema_version must be 1")
    if payload.get("status") != "complete":
        raise ValueError("baseline manifest status must be complete")
    stack_digest = _required_string(payload, "stack_digest")
    polarization = _required_string(payload, "polarization").upper()
    reference_date = _date(payload.get("reference_date"), "baseline reference_date")
    network_type = _required_string(payload, "network_type").upper()
    if network_type not in {"DSI", "SBAS", "PSI"}:
        raise ValueError("baseline manifest network_type must be DSI, SBAS, or PSI")
    raw_network = Path(_required_string(payload, "network_path"))
    if raw_network.is_absolute() or ".." in raw_network.parts:
        raise ValueError("baseline manifest network path must be relative and cannot traverse")
    network_path = validate_within_root(
        source.parent / raw_network, root, "baseline network"
    )
    try:
        network_path.relative_to(source.parent)
    except ValueError as error:
        raise ValueError("baseline manifest network path must stay beside the manifest") from error
    pair_count = payload.get("pair_count")
    if not isinstance(pair_count, int) or isinstance(pair_count, bool) or pair_count <= 0:
        raise ValueError("baseline manifest pair_count must be a positive integer")
    return BaselineManifest(
        source_path=source,
        stack_digest=stack_digest,
        polarization=polarization,
        reference_date=reference_date,
        network_type=network_type,
        network_path=network_path,
    )


def _network_pairs(path: Path, stack_dates: tuple[str, ...]) -> tuple[InterferogramPair, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"baseline network not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"baseline network is empty: {path}")
    available = set(stack_dates)
    directed: set[tuple[str, str]] = set()
    undirected: set[frozenset[str]] = set()
    pairs: list[InterferogramPair] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            raise ValueError(f"cannot parse baseline network line {line_number}: {raw}")
        master = _date(fields[0], f"network line {line_number} master")
        slave = _date(fields[1], f"network line {line_number} slave")
        if master not in available or slave not in available:
            missing = master if master not in available else slave
            raise ValueError(f"network date is not present in registered stack: {missing}")
        if master == slave:
            raise ValueError(f"baseline network contains self pair: {master}-{slave}")
        key = (master, slave)
        if key in directed:
            raise ValueError(f"baseline network contains duplicate pair: {master}-{slave}")
        unordered = frozenset(key)
        if unordered in undirected:
            raise ValueError(f"baseline network contains reversed pair: {master}-{slave}")
        directed.add(key)
        undirected.add(unordered)
        pairs.append(InterferogramPair(master=master, slave=slave))
    if not pairs:
        raise ValueError(f"baseline network contains no pairs: {path}")
    return tuple(pairs)


def _filter_flags(sensor: str, policy: str) -> tuple[int, int]:
    if policy == "on":
        return 1, 1
    if policy == "off":
        return 0, 0
    normalized = sensor.lower().replace("-", "").replace("_", "")
    return (0, 0) if normalized in {"sentinel1", "s1"} else (1, 1)


def build_gamma_interferogram_plan(
    case: GammaInterferogramCase,
) -> GammaInterferogramPlan:
    """Validate stack, baseline identity and network before GAMMA execution."""

    if not isinstance(case, GammaInterferogramCase):
        raise TypeError("case must be GammaInterferogramCase")
    stack = read_registered_stack(
        case.registered_stack,
        project_root=case.project_root,
        polarization=case.polarization,
    )
    baseline = read_baseline_manifest(
        case.baseline_manifest, project_root=case.project_root
    )
    if baseline.stack_digest != stack.source_digest:
        raise ValueError("baseline manifest stack_digest does not match registered stack")
    if baseline.reference_date != stack.reference_date:
        raise ValueError("baseline manifest reference_date does not match registered stack")
    if baseline.polarization != case.polarization:
        raise ValueError("baseline manifest polarization does not match requested polarization")

    radar_height = validate_within_root(
        case.radar_height, case.project_root, "radar height"
    )
    if not radar_height.is_file():
        raise FileNotFoundError(f"radar height not found: {radar_height}")
    if radar_height.stat().st_size == 0:
        raise ValueError(f"radar height is empty: {radar_height}")

    pairs = _network_pairs(baseline.network_path, stack.dates)
    flags = _filter_flags(stack.sensor, case.spectral_filter)
    return GammaInterferogramPlan(
        case=case,
        stack=stack,
        baseline=baseline,
        pairs=pairs,
        spectral_filter_range=flags[0],
        spectral_filter_azimuth=flags[1],
    )


__all__ = ["build_gamma_interferogram_plan", "read_baseline_manifest"]
