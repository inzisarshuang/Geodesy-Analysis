"""Strict read-only contract for PRE registered-stack manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from geodesy_analysis.common.paths import validate_within_root


@dataclass(frozen=True)
class RegisteredAsset:
    """One dated, polarized registered complex raster and parameter file."""

    date: str
    polarization: str
    data_path: Path
    parameter_path: Path


@dataclass(frozen=True)
class RegisteredStack:
    """Validated Analysis view of one complete PRE registered stack."""

    source_path: Path
    source_digest: str
    sensor: str
    reference_date: str
    dates: tuple[str, ...]
    polarizations: tuple[str, ...]
    assets: tuple[RegisteredAsset, ...]


def _valid_date(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}") from error
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must contain non-empty strings")
    parsed = tuple(value)
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label} must be unique")
    return parsed


def _asset_path(
    value: object,
    *,
    manifest_dir: Path,
    project_root: Path,
    label: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must be relative and cannot traverse: {value}")
    resolved = validate_within_root(manifest_dir / relative, project_root, label)
    validate_within_root(resolved, manifest_dir, label)
    if not resolved.is_file():
        raise FileNotFoundError(f"missing {label}: {resolved}")
    if resolved.stat().st_size == 0:
        raise ValueError(f"empty {label}: {resolved}")
    return resolved


def read_registered_stack(
    path: Path,
    *,
    project_root: Path,
    polarization: str,
) -> RegisteredStack:
    """Read one complete GAMMA radar-grid stack for a requested polarization."""

    root = Path(project_root).expanduser().resolve(strict=True)
    source = validate_within_root(Path(path), root, "registered stack")
    if not source.is_file():
        raise FileNotFoundError(f"registered stack manifest not found: {source}")
    encoded = source.read_bytes()
    if not encoded:
        raise ValueError(f"registered stack manifest is empty: {source}")
    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid registered stack JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("registered stack root must be a JSON object")
    if payload.get("schema_version") != 2:
        raise ValueError("registered stack schema_version must be 2")
    if payload.get("status") != "complete":
        raise ValueError("registered stack status must be complete")
    backend = payload.get("backend")
    if not isinstance(backend, dict) or str(backend.get("name", "")).lower() != "gamma":
        raise ValueError("registered stack backend must be gamma")
    if str(payload.get("geometry_type", "")).lower() != "radar_grid":
        raise ValueError("registered stack geometry_type must be radar_grid")

    sensor = payload.get("sensor")
    if not isinstance(sensor, str) or not sensor.strip():
        raise ValueError("registered stack sensor is required")
    dates = tuple(
        _valid_date(value, "registered stack date")
        for value in _string_tuple(payload.get("dates"), "registered stack dates")
    )
    reference_date = _valid_date(payload.get("reference_date"), "reference_date")
    if reference_date not in dates:
        raise ValueError("reference_date must occur in registered stack dates")
    declared_polarizations = tuple(
        value.upper()
        for value in _string_tuple(
            payload.get("polarizations"), "registered stack polarizations"
        )
    )
    if len(set(declared_polarizations)) != len(declared_polarizations):
        raise ValueError("registered stack polarizations must be unique")
    selected = str(polarization).strip().upper()
    if selected not in declared_polarizations:
        raise ValueError(f"registered stack does not contain polarization {selected}")

    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ValueError("registered stack assets must be a non-empty list")
    manifest_dir = source.parent
    all_assets: dict[tuple[str, str], RegisteredAsset] = {}
    for index, raw in enumerate(raw_assets, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"registered stack asset {index} must be an object")
        date = _valid_date(raw.get("date"), f"asset {index} date")
        asset_polarization = str(raw.get("polarization", "")).strip().upper()
        if date not in dates:
            raise ValueError(f"asset {index} date is not declared: {date}")
        if asset_polarization not in declared_polarizations:
            raise ValueError(
                f"asset {index} polarization is not declared: {asset_polarization}"
            )
        key = (date, asset_polarization)
        if key in all_assets:
            raise ValueError(f"duplicate registered asset: {date}/{asset_polarization}")
        all_assets[key] = RegisteredAsset(
            date=date,
            polarization=asset_polarization,
            data_path=_asset_path(
                raw.get("data_path"),
                manifest_dir=manifest_dir,
                project_root=root,
                label="asset data",
            ),
            parameter_path=_asset_path(
                raw.get("parameter_path"),
                manifest_dir=manifest_dir,
                project_root=root,
                label="asset parameter",
            ),
        )

    selected_assets: list[RegisteredAsset] = []
    for date in dates:
        key = (date, selected)
        if key not in all_assets:
            raise ValueError(f"missing asset for date {date} polarization {selected}")
        selected_assets.append(all_assets[key])

    return RegisteredStack(
        source_path=source,
        source_digest=hashlib.sha256(encoded).hexdigest(),
        sensor=sensor.strip().lower(),
        reference_date=reference_date,
        dates=dates,
        polarizations=declared_polarizations,
        assets=tuple(selected_assets),
    )


__all__ = ["RegisteredAsset", "RegisteredStack", "read_registered_stack"]
