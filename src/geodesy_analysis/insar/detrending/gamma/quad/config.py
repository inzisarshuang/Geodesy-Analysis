"""Strict project configuration for GAMMA quad detrending."""

from __future__ import annotations

import configparser
import math
import re
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    AnalysisCasePaths,
    bind_analysis_case,
    resolve_project_or_absolute_path,
)
from geodesy_analysis.common.product_layout import AnalysisProductLayout

from .models import GammaQuadDetrendCase

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DEFAULTS = {
    "coherence_threshold": "0.15",
    "trend_model": "0",
    "intensity_background": "true",
}
_KEYS = set(_DEFAULTS) | {
    "project",
    "case_root",
    "processing_root",
    "unwrapping_manifest",
    "output_dir",
    "figure_dir",
    "visualization_dir",
}


def _unknown(section: configparser.SectionProxy, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _overlaps(first: Path, second: Path) -> bool:
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


def _automatic_output(manifest: Path, case_root: Path) -> Path:
    for ancestor in manifest.parents:
        if ancestor == case_root.parent:
            break
        if ancestor.name == "ANALYSIS":
            try:
                ancestor.relative_to(case_root)
            except ValueError:
                break
            return (ancestor / "DETRENDING" / "GAMMA_QUAD").resolve()
    raise ValueError(
        "output_dir is required when unwrapping_manifest has no case-local ANALYSIS ancestor"
    )


def _resolve_visualization(
    paths: AnalysisCasePaths,
    value: str,
    *,
    output: Path,
    inputs: tuple[Path, ...],
) -> Path:
    visualization = resolve_project_or_absolute_path(
        paths, value, "quad detrending visualization output"
    )
    for protected in (output, *inputs):
        if _overlaps(visualization, protected):
            raise ValueError(
                "visualization output must not overlap scientific output or input: "
                f"{visualization} overlaps {protected.resolve()}"
            )
    return visualization


def load_gamma_quad_detrend_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaQuadDetrendCase, ...]:
    """Read ordered quad-detrending cases from one strict project CFG."""

    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA quad detrending configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_text = parser["project"].get("root", "").strip()
    if not root_text:
        raise ValueError(f"{source}: [project] root is required")
    raw_root = Path(root_text).expanduser()
    root = (raw_root if raw_root.is_absolute() else source.parent / raw_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{source}: project root is not a directory: {root}")

    defaults = dict(_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, set(_DEFAULTS))
        defaults.update((key, value.strip()) for key, value in parser["defaults"].items())

    case_sections = [
        name for name in parser.sections() if name not in {"project", "defaults"}
    ]
    unsupported = next((name for name in case_sections if not name.startswith("case:")), None)
    if unsupported is not None:
        raise ValueError(f"{source}: unsupported section [{unsupported}]")
    if case_name is not None:
        selected_section = f"case:{case_name}"
        if selected_section not in case_sections:
            raise ValueError(f"unknown case: {case_name}")
        case_sections = [selected_section]

    cases: list[GammaQuadDetrendCase] = []
    for section_name in case_sections:
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source, _KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        project_value = values.get("project", "") or values.get("case_root", "")
        missing = [key for key in ("unwrapping_manifest",) if not values.get(key)]
        if not project_value:
            missing.append("project/case_root")
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        processing_value = values.get("processing_root", "").strip() or None
        paths = bind_analysis_case(root, name, project_value, processing_value)
        layout = AnalysisProductLayout(paths) if processing_value is not None else None
        manifest = resolve_project_or_absolute_path(
            paths, values["unwrapping_manifest"], "unwrapping manifest"
        )
        if not manifest.is_file():
            raise FileNotFoundError(f"unwrapping manifest does not exist: {manifest}")
        try:
            threshold = float(values["coherence_threshold"])
        except ValueError as error:
            raise ValueError(
                f"{source}: coherence_threshold must be between 0 and 1"
            ) from error
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError(f"{source}: coherence_threshold must be between 0 and 1")
        try:
            trend_model = int(values["trend_model"])
        except ValueError as error:
            raise ValueError(f"{source}: trend_model must be an integer from 0 to 7") from error
        if trend_model not in range(8):
            raise ValueError(f"{source}: trend_model must be an integer from 0 to 7")
        intensity_background_text = values["intensity_background"].casefold()
        if intensity_background_text not in {"true", "false"}:
            raise ValueError(
                f"{source}: intensity_background must be true or false"
            )
        intensity_background = intensity_background_text == "true"

        pair_list = _case_pair_list(paths)
        output_text = values.get("output_dir", "").strip()
        output = (
            resolve_project_or_absolute_path(paths, output_text, "quad detrending output")
            if output_text
            else (
                layout.product("DETRENDING", "GAMMA_QUAD")
                if layout is not None
                else _automatic_output(manifest, paths.case_root)
            )
        )
        protected_inputs = (manifest.parent,) + (
            (pair_list,) if pair_list is not None else ()
        )
        if any(_overlaps(output, item) for item in protected_inputs):
            raise ValueError("quad detrending output must not overlap input or pair list")
        visualization_text = (
            values.get("figure_dir", "").strip()
            or values.get("visualization_dir", "").strip()
        )
        visualization = _resolve_visualization(
            paths,
            visualization_text
            or (
                layout.serialize(layout.figures("DETRENDING", "GAMMA_QUAD"))
                if layout is not None
                else f"{paths.case_id}/VISUALIZATION/DETRENDING/GAMMA_QUAD"
            ),
            output=output,
            inputs=protected_inputs,
        )
        log_directory = (
            layout.logs("DETRENDING", "GAMMA_QUAD")
            if layout is not None
            else paths.case_root / "LOG" / "ANALYSIS" / "DETRENDING" / "GAMMA_QUAD"
        )
        if any(
            _overlaps(candidate, log_directory)
            for candidate in (output, visualization, *((pair_list,) if pair_list else ()))
        ):
            raise ValueError("quad detrending paths must not overlap the log directory")
        cases.append(
            GammaQuadDetrendCase(
                paths=paths,
                unwrapping_manifest=manifest,
                coherence_threshold=threshold,
                trend_model=trend_model,
                output_dir=output,
                visualization_dir=visualization,
                pair_list=pair_list,
                intensity_background=intensity_background,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)
__all__ = ["load_gamma_quad_detrend_config"]
