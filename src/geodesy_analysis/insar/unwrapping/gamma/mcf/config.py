"""Strict project configuration for GAMMA MCF unwrapping."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    AnalysisCasePaths,
    bind_analysis_case,
    resolve_case_input,
    resolve_project_or_absolute_path,
)
from geodesy_analysis.common.product_layout import AnalysisProductLayout

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
_KEYS = set(_DEFAULTS) | {
    "project",
    "case_root",
    "processing_root",
    "filtering_manifest",
    "output_dir",
    "figure_dir",
    "visualization_dir",
}
_DEFAULT_KEYS = set(_DEFAULTS)


def _unknown(section, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _paths_overlap(first: Path, second: Path) -> bool:
    left = first.resolve()
    right = second.resolve()
    return left == right or left in right.parents or right in left.parents


def _case_pair_list(paths: AnalysisCasePaths) -> Path | None:
    candidate = (paths.processing_root or paths.case_root) / "pairs.txt"
    if candidate.is_symlink():
        raise ValueError(f"case pair list must not be a symlink: {candidate}")
    if not candidate.exists():
        return None
    if not candidate.is_file():
        raise ValueError(f"case pair list must be a regular file: {candidate}")
    return candidate.resolve()


def _resolve_visualization_output(
    paths: AnalysisCasePaths,
    value: str,
    *,
    scientific_output: Path,
    input_directory: Path,
    external_mask: Path | None,
    pair_list: Path | None,
) -> Path:
    visualization = resolve_project_or_absolute_path(
        paths, value, "unwrapping visualization output"
    )
    protected = (
        (scientific_output, input_directory)
        + ((external_mask,) if external_mask is not None else ())
        + ((pair_list,) if pair_list is not None else ())
    )
    for path in protected:
        if _paths_overlap(visualization, path):
            raise ValueError(
                "visualization output must not overlap scientific output or input: "
                f"{visualization} overlaps {path.resolve()}"
            )
    return visualization


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
    raise ValueError(
        "output_dir is required when filtering_manifest has no case-local ANALYSIS ancestor"
    )


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


def load_gamma_mcf_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaMcfCase, ...]:
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
    case_sections = [
        section_name
        for section_name in parser.sections()
        if section_name not in {"project", "defaults"}
    ]
    unsupported = next(
        (name for name in case_sections if not name.startswith("case:")), None
    )
    if unsupported is not None:
        raise ValueError(f"{source}: unsupported section [{unsupported}]")
    if case_name is not None:
        selected_section = f"case:{case_name}"
        if selected_section not in case_sections:
            raise ValueError(f"unknown case: {case_name}")
        case_sections = [selected_section]

    cases: list[GammaMcfCase] = []
    for section_name in case_sections:
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name")
        section = parser[section_name]
        _unknown(section, source, _KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        project_value = values.get("project", "") or values.get("case_root", "")
        missing = [key for key in ("filtering_manifest",) if not values.get(key)]
        if not project_value:
            missing.append("project/case_root")
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        processing_value = values.get("processing_root", "").strip() or None
        paths = bind_analysis_case(root, name, project_value, processing_value)
        layout = AnalysisProductLayout(paths) if processing_value is not None else None
        manifest = resolve_project_or_absolute_path(
            paths, values["filtering_manifest"], "filtering manifest"
        )
        pair_list = _case_pair_list(paths)
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
        output = (
            resolve_project_or_absolute_path(paths, output_text, "unwrapping output")
            if output_text
            else (
                layout.product("UNW", "GAMMA_MCF")
                if layout is not None
                else _automatic_output(manifest, paths.case_root)
            )
        )
        if _paths_overlap(output, manifest.parent) or (
            pair_list is not None and _paths_overlap(output, pair_list)
        ):
            raise ValueError(
                "unwrapping output must not overlap filtering inputs: "
                f"{output} overlaps a filtering or pair-selection input"
            )
        if external is not None and _paths_overlap(output, external):
            raise ValueError(
                "unwrapping output must not overlap external mask input: "
                f"{output} overlaps {external.resolve()}"
            )
        visualization_text = (
            values.get("figure_dir", "").strip()
            or values.get("visualization_dir", "").strip()
        )
        visualization = _resolve_visualization_output(
            paths,
            visualization_text
            or (
                layout.serialize(layout.figures("UNW", "GAMMA_MCF"))
                if layout is not None
                else f"{paths.case_id}/VISUALIZATION/UNWRAPPING/GAMMA_MCF"
            ),
            scientific_output=output,
            input_directory=manifest.parent,
            external_mask=external,
            pair_list=pair_list,
        )
        log_directory = (
            layout.logs("UNW", "GAMMA_MCF")
            if layout is not None
            else paths.case_root / "LOG" / "ANALYSIS" / "UNWRAPPING" / "GAMMA_MCF"
        )
        if pair_list is not None and _paths_overlap(pair_list, log_directory):
            raise ValueError(
                "pair list must not overlap the MCF log directory: "
                f"{pair_list} overlaps {log_directory.resolve()}"
            )
        if any(
            _paths_overlap(candidate, log_directory)
            for candidate in (output, visualization)
        ):
            raise ValueError(
                "unwrapping output directories must not overlap the log directory: "
                f"{log_directory}"
            )
        cases.append(
            GammaMcfCase(
                paths=paths,
                filtering_manifest=manifest,
                pair_list=pair_list,
                mcf_mode=mode,
                reference_mode=reference_mode,
                reference_range=reference_range,
                reference_azimuth=reference_azimuth,
                coherence_threshold=threshold,
                external_mask=external,
                mask_operation=operation,
                output_dir=output,
                visualization_dir=visualization,
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
