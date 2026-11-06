"""Strict method-centric configuration for GAMMA atmosphere correction."""

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

from .models import GammaAtmosphereCase, GammaAtmosphereMethod

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_METHOD_IDENTITIES: dict[str, str] = {
    "none": "NONE",
    "gamma_atm_mod_2d_auto": "GAMMA_ATM_MOD_2D_AUTO",
    "gamma_atm_mod_2d_polygon": "GAMMA_ATM_MOD_2D_POLYGON",
    "gamma_fspf_atm_mod_2d": "GAMMA_FSPF_ATM_MOD_2D",
}
_METHOD_DEFAULTS = {
    "none": (256, 256, 128, 128),
    "gamma_atm_mod_2d_auto": (256, 256, 128, 128),
    "gamma_atm_mod_2d_polygon": (16, 16, 8, 8),
    "gamma_fspf_atm_mod_2d": (8, 8, 4, 4),
}
_DEFAULTS = {
    "height_correlation_threshold": "0.1",
    "intensity_background": "true",
}
_PARAMETER_KEYS = set(_DEFAULTS) | {
    "fit_window_range",
    "fit_window_azimuth",
    "fit_step_range",
    "fit_step_azimuth",
    "fspf_mode",
    "fspf_window_size",
    "fspf_overlap",
}
_KEYS = _PARAMETER_KEYS | {
    "project",
    "case_root",
    "processing_root",
    "detrending_manifest",
    "method",
    "output_dir",
    "figure_dir",
    "log_dir",
    "polygon_file",
}


def _unknown(
    section: configparser.SectionProxy, source: Path, allowed: set[str]
) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _declared_path(
    paths: AnalysisCasePaths, value: str, label: str, *, must_exist: bool
) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else paths.project_root / raw
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    resolved = resolve_project_or_absolute_path(paths, value, label)
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _positive_integer(source: Path, key: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{source}: {key} must be a positive integer")
    return parsed


def _boolean(source: Path, key: str, value: str) -> bool:
    normalized = value.casefold()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{source}: {key} must be true or false")
    return normalized == "true"


def load_gamma_atmosphere_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaAtmosphereCase, ...]:
    """Read ordered atmosphere cases without creating output directories."""

    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(
            f"invalid GAMMA atmosphere configuration {source}: {error}"
        ) from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_value = parser["project"].get("root", "").strip()
    if not root_value:
        raise ValueError(f"{source}: [project] root is required")
    raw_root = Path(root_value).expanduser()
    root = (
        raw_root if raw_root.is_absolute() else source.parent / raw_root
    ).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{source}: project root is not a directory: {root}")

    defaults = dict(_DEFAULTS)
    default_keys: set[str] = set()
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, _PARAMETER_KEYS)
        defaults.update(
            (key, value.strip()) for key, value in parser["defaults"].items()
        )
        default_keys = set(parser["defaults"])

    sections = [
        name for name in parser.sections() if name not in {"project", "defaults"}
    ]
    unsupported = next(
        (name for name in sections if not name.startswith("case:")), None
    )
    if unsupported is not None:
        raise ValueError(f"{source}: unsupported section [{unsupported}]")
    if case_name is not None:
        selected = f"case:{case_name}"
        if selected not in sections:
            raise ValueError(f"unknown case: {case_name}")
        sections = [selected]

    cases: list[GammaAtmosphereCase] = []
    for section_name in sections:
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source, _KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        project_value = values.get("project", "") or values.get("case_root", "")
        missing = [
            key
            for key in ("processing_root", "detrending_manifest", "method")
            if not values.get(key)
        ]
        if not project_value:
            missing.append("project/case_root")
        if missing:
            raise ValueError(
                f"{source}: [{section_name}] missing keys: {', '.join(missing)}"
            )
        method_value = values["method"]
        if method_value not in _METHOD_IDENTITIES:
            raise ValueError(f"{source}: unsupported atmosphere method: {method_value}")
        method: GammaAtmosphereMethod = method_value  # type: ignore[assignment]
        paths = bind_analysis_case(
            root, name, project_value, values["processing_root"]
        )
        layout = AnalysisProductLayout(paths)
        manifest = _declared_path(
            paths,
            values["detrending_manifest"],
            "detrending manifest",
            must_exist=True,
        )
        polygon_value = values.get("polygon_file", "").strip()
        if method == "gamma_atm_mod_2d_polygon":
            if not polygon_value:
                raise ValueError(f"{source}: polygon_file is required for polygon method")
            polygon = _declared_path(
                paths, polygon_value, "polygon file", must_exist=True
            )
            if polygon.stat().st_size < 1:
                raise ValueError(f"{source}: polygon file must not be empty")
        else:
            if polygon_value:
                raise ValueError(
                    f"{source}: polygon_file is only valid for polygon method"
                )
            polygon = None

        explicit_fspf = ({"fspf_mode", "fspf_window_size", "fspf_overlap"} & set(section))
        explicit_fspf |= {
            "fspf_mode",
            "fspf_window_size",
            "fspf_overlap",
        } & default_keys
        if method != "gamma_fspf_atm_mod_2d" and explicit_fspf:
            raise ValueError(f"{source}: FSPF keys are only valid for FSPF method")

        method_defaults = _METHOD_DEFAULTS[method]
        for key, default in zip(
            (
                "fit_window_range",
                "fit_window_azimuth",
                "fit_step_range",
                "fit_step_azimuth",
            ),
            method_defaults,
        ):
            values.setdefault(key, str(default))
        parsed_windows = {
            key: _positive_integer(source, key, values[key])
            for key in (
                "fit_window_range",
                "fit_window_azimuth",
                "fit_step_range",
                "fit_step_azimuth",
            )
        }
        try:
            threshold = float(values["height_correlation_threshold"])
        except ValueError as error:
            raise ValueError(
                f"{source}: height_correlation_threshold must be between 0 and 1"
            ) from error
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError(
                f"{source}: height_correlation_threshold must be between 0 and 1"
            )
        intensity = _boolean(
            source, "intensity_background", values["intensity_background"]
        )
        fspf_mode = _positive_integer(
            source, "fspf_mode", values.get("fspf_mode", "2")
        )
        fspf_window = _positive_integer(
            source, "fspf_window_size", values.get("fspf_window_size", "256")
        )
        fspf_overlap = _positive_integer(
            source, "fspf_overlap", values.get("fspf_overlap", "4")
        )
        if fspf_overlap >= fspf_window:
            raise ValueError(f"{source}: fspf_overlap must be smaller than fspf_window_size")

        identity = _METHOD_IDENTITIES[method]
        output = _declared_path(
            paths,
            values.get("output_dir", "")
            or layout.serialize(layout.product("ATMOSPHERE", identity)),
            "atmosphere output",
            must_exist=False,
        )
        figures = _declared_path(
            paths,
            values.get("figure_dir", "")
            or layout.serialize(layout.figures("ATMOSPHERE", identity)),
            "atmosphere figure output",
            must_exist=False,
        )
        logs = _declared_path(
            paths,
            values.get("log_dir", "")
            or layout.serialize(layout.logs("ATMOSPHERE", identity)),
            "atmosphere log output",
            must_exist=False,
        )
        layout.require_disjoint(
            science=output,
            figures=figures,
            logs=logs,
            inputs=(manifest, *((polygon,) if polygon is not None else ())),
        )
        cases.append(
            GammaAtmosphereCase(
                paths=paths,
                detrending_manifest=manifest,
                method=method,
                output_dir=output,
                figure_dir=figures,
                log_dir=logs,
                intensity_background=intensity,
                fit_window_range=parsed_windows["fit_window_range"],
                fit_window_azimuth=parsed_windows["fit_window_azimuth"],
                fit_step_range=parsed_windows["fit_step_range"],
                fit_step_azimuth=parsed_windows["fit_step_azimuth"],
                height_correlation_threshold=threshold,
                polygon_file=polygon,
                fspf_mode=fspf_mode,
                fspf_window_size=fspf_window,
                fspf_overlap=fspf_overlap,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


__all__ = ["load_gamma_atmosphere_config"]
