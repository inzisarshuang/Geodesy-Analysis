"""Strict project configuration for GAMMA MCF unwrapping."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.case_paths import bind_analysis_case, resolve_case_input

from .models import GammaMcfCase

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DEFAULTS = {
    "mcf_mode": "0",
    "reference_mode": "auto",
    "reference_range": "",
    "reference_azimuth": "",
    "coherence_threshold": "0.3",
    "external_mask": "",
    "mask_operation": "and",
}
_KEYS = set(_DEFAULTS) | {"case_root", "filtering_manifest", "output_dir"}
_DEFAULT_KEYS = set(_DEFAULTS)


def _unknown(section, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


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


def _automatic_output(manifest: Path, case_root: Path) -> Path:
    for ancestor in manifest.parents:
        if ancestor == case_root.parent:
            break
        if ancestor.name == "ANALYSIS":
            try:
                ancestor.relative_to(case_root)
            except ValueError:
                break
            return (ancestor / "UNWRAPPING" / "GAMMA_MCF").resolve()
    raise ValueError("output_dir is required when filtering_manifest has no case-local ANALYSIS ancestor")


def _coordinate(values: dict[str, str], key: str, source: Path) -> int | None:
    text = values[key].strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a nonnegative integer") from error
    if value < 0:
        raise ValueError(f"{source}: {key} must be a nonnegative integer")
    return value


def load_gamma_mcf_config(path: Path) -> tuple[GammaMcfCase, ...]:
    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA MCF configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_text = parser["project"].get("root", "").strip()
    if not root_text:
        raise ValueError(f"{source}: [project] root is required")
    raw_root = Path(root_text).expanduser()
    root = (raw_root if raw_root.is_absolute() else source.parent / raw_root).resolve(strict=True)
    defaults = dict(_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, _DEFAULT_KEYS)
        defaults.update((key, value.strip()) for key, value in parser["defaults"].items())
    cases: list[GammaMcfCase] = []
    for section_name in parser.sections():
        if section_name in {"project", "defaults"}:
            continue
        if not section_name.startswith("case:"):
            raise ValueError(f"{source}: unsupported section [{section_name}]")
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name")
        section = parser[section_name]
        _unknown(section, source, _KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        missing = [key for key in ("case_root", "filtering_manifest") if not values.get(key)]
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        paths = bind_analysis_case(root, name, values["case_root"])
        manifest = resolve_case_input(paths, values["filtering_manifest"])
        try:
            mode = int(values["mcf_mode"])
        except ValueError as error:
            raise ValueError(f"{source}: mcf_mode must be 0 through 3") from error
        if mode not in {0, 1, 2, 3}:
            raise ValueError(f"{source}: mcf_mode must be 0 through 3")
        reference_mode = values["reference_mode"].lower()
        if reference_mode not in {"auto", "manual"}:
            raise ValueError(f"{source}: reference_mode must be auto or manual")
        reference_range = _coordinate(values, "reference_range", source)
        reference_azimuth = _coordinate(values, "reference_azimuth", source)
        if reference_mode == "manual" and (reference_range is None or reference_azimuth is None):
            raise ValueError(f"{source}: manual reference requires reference_range and reference_azimuth")
        try:
            threshold = float(values["coherence_threshold"])
        except ValueError as error:
            raise ValueError(f"{source}: coherence_threshold must be between 0 and 1") from error
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError(f"{source}: coherence_threshold must be between 0 and 1")
        operation = values["mask_operation"].lower()
        if operation not in {"and", "or", "xor"}:
            raise ValueError(f"{source}: mask_operation must be and, or, or xor")
        external = resolve_case_input(paths, values["external_mask"]) if values["external_mask"] else None
        output_text = values.get("output_dir", "").strip()
        output = _project_output(root, output_text) if output_text else _automatic_output(manifest, paths.case_root)
        cases.append(
            GammaMcfCase(
                paths=paths,
                filtering_manifest=manifest,
                mcf_mode=mode,
                reference_mode=reference_mode,
                reference_range=reference_range,
                reference_azimuth=reference_azimuth,
                coherence_threshold=threshold,
                external_mask=external,
                mask_operation=operation,
                output_dir=output,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


def select_gamma_mcf_case(cases: Sequence[GammaMcfCase], name: str | None) -> GammaMcfCase:
    if name is None:
        if len(cases) != 1:
            raise ValueError("--case is required when configuration has multiple cases")
        return cases[0]
    for case in cases:
        if case.name == name:
            return case
    raise ValueError(f"unknown case: {name}")


__all__ = ["load_gamma_mcf_config", "select_gamma_mcf_case"]
