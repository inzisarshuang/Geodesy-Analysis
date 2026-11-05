"""Validate detrending lineage and build a side-effect-free GAMMA quad plan."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from geodesy_analysis.common.case_paths import resolve_project_or_absolute_path
from geodesy_analysis.insar.filtering.publication import ensure_nonempty, gamma_parameter

from .models import GammaQuadDetrendCase, GammaQuadDetrendPlan, GammaQuadPair

_PAIR = re.compile(r"(\d{8})-(\d{8})\Z")


def _digest(payload: dict[str, object], raw: bytes) -> str:
    supplied = payload.get("scientific_manifest_digest")
    if supplied is not None:
        if not isinstance(supplied, str) or re.fullmatch(r"[0-9a-f]{64}", supplied) is None:
            raise ValueError("manifest scientific_manifest_digest is invalid")
        return supplied
    return hashlib.sha256(raw).hexdigest()


def _manifest(path: Path, label: str) -> tuple[dict[str, object], bytes, str]:
    source = ensure_nonempty(path, label)
    raw = source.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid {label} JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw, _digest(payload, raw)


def _product(base: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"manifest {label} path is unsafe")
    target = (base / relative).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"manifest {label} leaves its product directory") from error
    return ensure_nonempty(target, label)


def _size(path: Path, expected: int, label: str) -> None:
    if path.stat().st_size != expected:
        raise ValueError(f"{label} byte size mismatch: {path.stat().st_size} != {expected}")


def _overlaps(first: Path, second: Path) -> bool:
    left = first.resolve()
    right = second.resolve()
    return left == right or left in right.parents or right in left.parents


def _read_pair_list(
    path: Path, available: dict[str, GammaQuadPair]
) -> tuple[tuple[GammaQuadPair, ...], str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"pair list must be UTF-8 text: {path}") from error
    selected: list[GammaQuadPair] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        name = raw_line.split("#", 1)[0].strip()
        if not name:
            continue
        if _PAIR.fullmatch(name) is None:
            raise ValueError(f"invalid pair list entry on line {line_number}: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate pair list entry on line {line_number}: {name}")
        if name not in available:
            raise ValueError(
                f"pair list entry has no unwrapped input in unwrapping manifest: {name}"
            )
        selected.append(available[name])
        seen.add(name)
    if not selected:
        raise ValueError(f"pair list contains no pairs: {path}")
    return tuple(selected), hashlib.sha256(raw).hexdigest()


def build_gamma_quad_detrend_plan(
    case: GammaQuadDetrendCase,
) -> GammaQuadDetrendPlan:
    if not isinstance(case, GammaQuadDetrendCase):
        raise TypeError("case must be GammaQuadDetrendCase")
    unwrap, _, unwrap_digest = _manifest(
        case.unwrapping_manifest, "unwrapping manifest"
    )
    if unwrap.get("schema_version") != 2 or unwrap.get("status") != "complete":
        raise ValueError("unwrapping manifest must be complete schema version 2")
    if unwrap.get("case_id") != case.case_id or unwrap.get("method") != "gamma_mcf":
        raise ValueError("unwrapping manifest case or method is inconsistent")
    grid = unwrap.get("grid")
    if not isinstance(grid, dict):
        raise ValueError("unwrapping manifest grid is required")
    width, lines = grid.get("width"), grid.get("lines")
    if not isinstance(width, int) or not isinstance(lines, int) or width <= 0 or lines <= 0:
        raise ValueError("unwrapping grid dimensions are invalid")
    float_size = width * lines * 4

    filtering_value = unwrap.get("filtering_manifest_project_path")
    if not isinstance(filtering_value, str):
        raise ValueError("unwrapping manifest filtering-manifest identity is required")
    filtering_path = resolve_project_or_absolute_path(
        case.paths, filtering_value, "filtering manifest"
    )
    filtering, _, filtering_digest = _manifest(
        filtering_path, "filtering manifest"
    )
    if filtering.get("schema_version") != 2 or filtering.get("status") != "complete":
        raise ValueError("filtering manifest must be complete schema version 2")
    if filtering.get("case_id") != case.case_id:
        raise ValueError("filtering manifest case_id does not match configured case")
    if unwrap.get("filtering_manifest_digest") != filtering_digest:
        raise ValueError("unwrapping manifest filtering digest does not match source")
    if filtering.get("grid") != {"lines": lines, "width": width}:
        raise ValueError("filtering and unwrapping grid dimensions differ")

    interferogram_value = filtering.get("interferogram_manifest_project_path")
    if not isinstance(interferogram_value, str):
        raise ValueError("filtering manifest interferogram identity is required")
    interferogram_path = resolve_project_or_absolute_path(
        case.paths, interferogram_value, "interferogram manifest"
    )
    interferogram, interferogram_raw, interferogram_digest = _manifest(
        interferogram_path, "interferogram manifest"
    )
    if interferogram.get("status") != "complete":
        raise ValueError("interferogram manifest must be complete")
    if filtering.get("interferogram_manifest_digest") != _digest(
        interferogram, interferogram_raw
    ):
        raise ValueError("filtering manifest interferogram digest does not match source")
    if interferogram.get("case_id") not in {None, case.case_id}:
        raise ValueError("interferogram manifest case_id does not match configured case")
    if interferogram.get("schema_version") != 2:
        raise ValueError("quad detrending requires a schema-v2 interferogram manifest")

    mli_assets = interferogram.get("mli_assets")
    if not isinstance(mli_assets, list) or not mli_assets:
        raise ValueError("interferogram manifest MLI inventory is missing")
    mli_by_date: dict[str, tuple[Path, Path]] = {}
    for asset in mli_assets:
        if not isinstance(asset, dict):
            raise ValueError("interferogram MLI item is invalid")
        date = asset.get("date")
        if not isinstance(date, str) or re.fullmatch(r"\d{8}", date) is None:
            raise ValueError("interferogram MLI date is invalid")
        if date in mli_by_date:
            raise ValueError(f"interferogram manifest has duplicate MLI date: {date}")
        mli = _product(interferogram_path.parent, asset.get("data_path"), "MLI")
        parameter = _product(
            interferogram_path.parent, asset.get("parameter_path"), "MLI parameter"
        )
        if (
            gamma_parameter(parameter, "range_samples") != width
            or gamma_parameter(parameter, "azimuth_lines") != lines
        ):
            raise ValueError(f"MLI parameter grid differs from unwrapped grid: {date}")
        _size(mli, float_size, "MLI")
        mli_by_date[date] = (mli, parameter)

    raw_filter_pairs = filtering.get("pairs")
    if not isinstance(raw_filter_pairs, list) or filtering.get("pair_count") != len(raw_filter_pairs):
        raise ValueError("filtering manifest pair inventory is incomplete")
    coherence_by_pair: dict[str, Path] = {}
    for item in raw_filter_pairs:
        if not isinstance(item, dict) or not isinstance(item.get("products"), dict):
            raise ValueError("filtering manifest pair item is invalid")
        name = item.get("pair")
        if not isinstance(name, str) or _PAIR.fullmatch(name) is None:
            raise ValueError("filtering manifest pair name is invalid")
        if name in coherence_by_pair:
            raise ValueError(f"filtering manifest contains duplicate pair: {name}")
        coherence = _product(
            filtering_path.parent,
            item["products"].get("filtered_coherence"),
            "filtered coherence",
        )
        _size(coherence, float_size, "filtered coherence")
        values = np.memmap(coherence, dtype=">f4", mode="r")
        valid_coherence = bool(
            np.all(np.isfinite(values))
            and np.all((values >= 0.0) & (values <= 1.0))
        )
        del values
        if not valid_coherence:
            raise ValueError(f"filtered coherence values are invalid: {name}")
        coherence_by_pair[name] = coherence
    if len(coherence_by_pair) != len(raw_filter_pairs):
        raise ValueError("filtering manifest contains duplicate pairs")
    interferogram_pairs = interferogram.get("pairs")
    if not isinstance(interferogram_pairs, list):
        raise ValueError("interferogram manifest pair inventory is missing")
    interferogram_names = [
        item.get("pair") for item in interferogram_pairs if isinstance(item, dict)
    ]
    if (
        len(interferogram_names) != len(interferogram_pairs)
        or any(not isinstance(name, str) or _PAIR.fullmatch(name) is None for name in interferogram_names)
        or len(set(interferogram_names)) != len(interferogram_names)
        or set(interferogram_names) != set(coherence_by_pair)
    ):
        raise ValueError("filtering and interferogram pair inventories are inconsistent")

    raw_pairs = unwrap.get("pairs")
    if not isinstance(raw_pairs, list) or unwrap.get("pair_count") != len(raw_pairs):
        raise ValueError("unwrapping manifest pair inventory is incomplete")
    pairs: dict[str, GammaQuadPair] = {}
    for item in raw_pairs:
        if not isinstance(item, dict):
            raise ValueError("unwrapping manifest pair item is invalid")
        name = item.get("pair")
        match = _PAIR.fullmatch(name) if isinstance(name, str) else None
        if match is None:
            raise ValueError("unwrapping manifest pair name is invalid")
        if name in pairs:
            raise ValueError(f"unwrapping manifest contains duplicate pair: {name}")
        if name not in coherence_by_pair:
            raise ValueError(f"unwrapped pair is missing from filtering manifest: {name}")
        master = mli_by_date.get(match.group(1))
        if master is None:
            raise ValueError(f"master MLI is missing from interferogram manifest: {match.group(1)}")
        unwrapped = _product(
            case.unwrapping_manifest.parent,
            item.get("unwrapped_path"),
            "unwrapped phase",
        )
        _size(unwrapped, float_size, "unwrapped phase")
        pairs[name] = GammaQuadPair(
            match.group(1),
            match.group(2),
            unwrapped,
            coherence_by_pair[name],
            master[0],
            master[1],
        )
    if not pairs:
        raise ValueError("unwrapping manifest contains no pairs")

    pair_list_digest = None
    if case.pair_list is None:
        selected = tuple(pairs[name] for name in sorted(pairs))
    else:
        selected, pair_list_digest = _read_pair_list(case.pair_list, pairs)
    if not selected:
        raise ValueError("no pairs selected for quad detrending")
    protected = (
        case.unwrapping_manifest,
        filtering_path,
        interferogram_path,
        *((case.pair_list,) if case.pair_list is not None else ()),
        *(path for pair in selected for path in (
            pair.unwrapped,
            pair.coherence,
            pair.master_mli,
            pair.master_mli_parameter,
        )),
    )
    log_dir = case.case_root / "LOG" / "ANALYSIS" / "DETRENDING" / "GAMMA_QUAD"
    for destination in (case.output_dir, case.visualization_dir, log_dir):
        for source in protected:
            if _overlaps(destination, source):
                raise ValueError(
                    f"quad detrending destination overlaps an input: "
                    f"{destination} overlaps {source}"
                )
    if _overlaps(case.output_dir, case.visualization_dir):
        raise ValueError("quad detrending scientific and visualization outputs overlap")
    if _overlaps(case.output_dir, log_dir) or _overlaps(case.visualization_dir, log_dir):
        raise ValueError("quad detrending outputs must not overlap the log directory")
    return GammaQuadDetrendPlan(
        case=case,
        pairs=selected,
        width=width,
        lines=lines,
        available_pair_count=len(pairs),
        unwrapping_manifest_digest=unwrap_digest,
        filtering_manifest=filtering_path,
        filtering_manifest_digest=filtering_digest,
        interferogram_manifest=interferogram_path,
        interferogram_manifest_digest=interferogram_digest,
        pair_list_digest=pair_list_digest,
    )


__all__ = ["build_gamma_quad_detrend_plan"]
