"""Strict project configuration for manifest-driven InSAR filtering."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case, resolve_case_input

from .models import FilteringCase, FilteringMethod

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_BUILTIN_DEFAULTS = {
    "search_window": "13",
    "patch_size": "3",
    "minimum_looks": "80",
    "likelihood_h": "",
    "coherence_window": "11",
    "filter_threshold": "0.3",
    "tile_size": "96",
    "point_threshold": "0.3",
    "seed": "20260717",
    "bm3d_mode": "1",
    "bm3d_sigma": "6",
    "bm3d_search_window": "10",
    "bm3d_block_size": "8",
    "bm3d_block_step": "16",
    "bm3d_group_size": "3",
    "bm3d_transform": "0",
    "adf_alpha": "0.4",
    "adf_first_window": "64",
    "adf_second_window": "16",
    "adf_steps": "5",
}
_VALUE_KEYS = set(_BUILTIN_DEFAULTS) | {
    "case_root",
    "interferogram_manifest",
    "method",
    "output_dir",
}
_DEFAULT_KEYS = _VALUE_KEYS - {"case_root", "interferogram_manifest", "output_dir"}


def _unknown(section: configparser.SectionProxy, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _integer(values: dict[str, str], key: str, source: Path, *, minimum: int = 1) -> int:
    try:
        value = int(values[key])
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be an integer") from error
    if value < minimum:
        qualifier = "nonnegative" if minimum == 0 else "positive"
        raise ValueError(f"{source}: {key} must be a {qualifier} integer")
    return value


def _float(values: dict[str, str], key: str, source: Path) -> float:
    try:
        value = float(values[key])
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a finite number") from error
    if not math.isfinite(value):
        raise ValueError(f"{source}: {key} must be a finite number")
    return value


def _unit_interval(values: dict[str, str], key: str, source: Path) -> float:
    value = _float(values, key, source)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{source}: {key} must be between 0 and 1")
    return value


def _project_output(root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        if "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("output_dir must be a POSIX project-relative path")
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"output_dir must stay inside project root: {resolved}") from error
    return resolved


def _automatic_output(manifest: Path, method: FilteringMethod, case_root: Path) -> Path:
    for ancestor in manifest.parents:
        if ancestor == case_root.parent:
            break
        if ancestor.name == "ANALYSIS":
            try:
                ancestor.relative_to(case_root)
            except ValueError:
                break
            return (ancestor / "FILTERING" / method.directory_name).resolve()
    raise ValueError("output_dir is required when interferogram_manifest has no case-local ANALYSIS ancestor")


def load_filtering_config(path: Path) -> tuple[FilteringCase, ...]:
    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid filtering configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    project = parser["project"]
    _unknown(project, source, {"root"})
    root_text = project.get("root", "").strip()
    if not root_text:
        raise ValueError(f"{source}: [project] root is required")
    raw_root = Path(root_text).expanduser()
    root = (raw_root if raw_root.is_absolute() else source.parent / raw_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{source}: project root is not a directory: {root}")

    defaults = dict(_BUILTIN_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, _DEFAULT_KEYS)
        defaults.update((key, value.strip()) for key, value in parser["defaults"].items())

    cases: list[FilteringCase] = []
    for section_name in parser.sections():
        if section_name in {"project", "defaults"}:
            continue
        if not section_name.startswith("case:"):
            raise ValueError(f"{source}: unsupported section [{section_name}]")
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source, _VALUE_KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        missing = [key for key in ("case_root", "interferogram_manifest", "method") if not values.get(key)]
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        try:
            method = FilteringMethod(values["method"].lower())
        except ValueError as error:
            raise ValueError(f"{source}: method must be nl_insar, gamma_bm3d, or gamma_adf") from error
        paths = bind_analysis_case(root, name, values["case_root"])
        manifest = resolve_case_input(paths, values["interferogram_manifest"])
        if not manifest.is_file():
            raise FileNotFoundError(f"interferogram manifest does not exist: {manifest}")
        output_text = values.get("output_dir", "").strip()
        output = _project_output(root, output_text) if output_text else _automatic_output(manifest, method, paths.case_root)

        odd_keys = ("search_window", "patch_size", "coherence_window")
        parsed_ints = {key: _integer(values, key, source) for key in odd_keys}
        for key in odd_keys:
            if parsed_ints[key] % 2 == 0:
                raise ValueError(f"{source}: {key} must be a positive odd integer")
        minimum_looks = _integer(values, "minimum_looks", source)
        if minimum_looks > parsed_ints["search_window"] ** 2:
            raise ValueError(f"{source}: minimum_looks exceeds the search-window sample count")
        likelihood_text = values["likelihood_h"].strip()
        likelihood_h = None
        if likelihood_text:
            likelihood_h = _float(values, "likelihood_h", source)
            if likelihood_h <= 0:
                raise ValueError(f"{source}: likelihood_h must be positive")
        cases.append(
            FilteringCase(
                paths=paths,
                interferogram_manifest=manifest,
                method=method,
                output_dir=output,
                search_window=parsed_ints["search_window"],
                patch_size=parsed_ints["patch_size"],
                minimum_looks=minimum_looks,
                likelihood_h=likelihood_h,
                coherence_window=parsed_ints["coherence_window"],
                filter_threshold=_unit_interval(values, "filter_threshold", source),
                tile_size=_integer(values, "tile_size", source),
                point_threshold=_unit_interval(values, "point_threshold", source),
                seed=_integer(values, "seed", source, minimum=0),
                bm3d_mode=_integer(values, "bm3d_mode", source),
                bm3d_sigma=_integer(values, "bm3d_sigma", source),
                bm3d_search_window=_integer(values, "bm3d_search_window", source),
                bm3d_block_size=_integer(values, "bm3d_block_size", source),
                bm3d_block_step=_integer(values, "bm3d_block_step", source),
                bm3d_group_size=_integer(values, "bm3d_group_size", source),
                bm3d_transform=_integer(values, "bm3d_transform", source, minimum=0),
                adf_alpha=_unit_interval(values, "adf_alpha", source),
                adf_first_window=_integer(values, "adf_first_window", source),
                adf_second_window=_integer(values, "adf_second_window", source),
                adf_steps=_integer(values, "adf_steps", source),
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


def select_filtering_case(cases: Sequence[FilteringCase], name: str | None) -> FilteringCase:
    if name is None:
        if len(cases) != 1:
            raise ValueError("--case is required when configuration has multiple cases")
        return cases[0]
    for case in cases:
        if case.name == name:
            return case
    raise ValueError(f"unknown case: {name}")


__all__ = ["load_filtering_config", "select_filtering_case"]
