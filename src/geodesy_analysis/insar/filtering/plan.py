"""Side-effect-free filtering plan built only from an interferogram manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .models import FilteringCase, FilteringPair, FilteringPlan, InterferogramManifest, MLIAsset
from .publication import ensure_nonempty, gamma_parameter

_PAIR = re.compile(r"(\d{8})-(\d{8})\Z")


def _asset(base: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"interferogram manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"interferogram manifest {label} path is unsafe")
    target = (base / relative).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"interferogram manifest {label} leaves its output directory") from error
    return ensure_nonempty(target, label)


def _exact_size(path: Path, expected: int, label: str) -> None:
    actual = path.stat().st_size
    if actual != expected:
        raise ValueError(f"{label} byte size mismatch: {actual} != {expected}: {path}")


def build_filtering_plan(case: FilteringCase) -> FilteringPlan:
    if not isinstance(case, FilteringCase):
        raise TypeError("case must be FilteringCase")
    source = ensure_nonempty(case.interferogram_manifest, "interferogram manifest")
    try:
        raw = source.read_bytes()
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid interferogram manifest JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("interferogram manifest root must be a JSON object")
    schema = payload.get("schema_version")
    if schema not in {1, 2}:
        raise ValueError("interferogram manifest schema_version must be 1 or 2")
    if payload.get("status") != "complete":
        raise ValueError("interferogram manifest status must be complete")
    case_id: str | None = None
    if schema == 2:
        case_id = payload.get("case_id") if isinstance(payload.get("case_id"), str) else None
        if case_id != case.case_id:
            raise ValueError("interferogram manifest case_id does not match configured case")

    raw_mli = payload.get("mli_assets")
    if not isinstance(raw_mli, list) or not raw_mli:
        raise ValueError("interferogram manifest mli_assets must be a nonempty list")
    assets: list[MLIAsset] = []
    by_date: dict[str, MLIAsset] = {}
    shape: tuple[int, int] | None = None
    for item in raw_mli:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str):
            raise ValueError("interferogram manifest MLI item is invalid")
        date = item["date"]
        if date in by_date:
            raise ValueError(f"interferogram manifest contains duplicate MLI date: {date}")
        data = _asset(source.parent, item.get("data_path"), "MLI")
        parameter = _asset(source.parent, item.get("parameter_path"), "MLI parameter file")
        current = (gamma_parameter(parameter, "range_samples"), gamma_parameter(parameter, "azimuth_lines"))
        if shape is None:
            shape = current
        elif current != shape:
            raise ValueError("interferogram manifest MLI shapes do not match")
        _exact_size(data, current[0] * current[1] * 4, "MLI")
        asset = MLIAsset(date=date, data_path=data, parameter_path=parameter)
        assets.append(asset)
        by_date[date] = asset
    assert shape is not None

    raw_pairs = payload.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("interferogram manifest pairs must be a nonempty list")
    pairs: list[FilteringPair] = []
    seen: set[str] = set()
    for item in raw_pairs:
        if not isinstance(item, dict) or not isinstance(item.get("products"), dict):
            raise ValueError("interferogram manifest pair item is invalid")
        name = item.get("pair")
        match = _PAIR.fullmatch(name) if isinstance(name, str) else None
        if match is None:
            raise ValueError(f"interferogram manifest pair name is invalid: {name!r}")
        if name in seen:
            raise ValueError(f"interferogram manifest contains duplicate pair: {name}")
        seen.add(name)
        master, slave = match.groups()
        if master not in by_date or slave not in by_date:
            raise ValueError(f"interferogram pair MLI is missing: {name}")
        tflt = _asset(source.parent, item["products"].get("differential_interferogram"), "differential interferogram")
        _exact_size(tflt, shape[0] * shape[1] * 8, "differential interferogram")
        pairs.append(
            FilteringPair(
                master=master,
                slave=slave,
                interferogram=tflt,
                master_mli=by_date[master].data_path,
                slave_mli=by_date[slave].data_path,
            )
        )
    pairs.sort(key=lambda pair: pair.name)
    manifest = InterferogramManifest(
        source_path=source,
        schema_version=schema,
        case_id=case_id,
        mli_assets=tuple(sorted(assets, key=lambda item: item.date)),
        source_digest=hashlib.sha256(raw).hexdigest(),
    )
    return FilteringPlan(case=case, manifest=manifest, pairs=tuple(pairs), width=shape[0], lines=shape[1])


__all__ = ["build_filtering_plan"]
