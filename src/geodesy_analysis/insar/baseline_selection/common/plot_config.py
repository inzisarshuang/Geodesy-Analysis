"""Project-confined configuration for standalone baseline-network plots."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from geodesy_analysis.common.paths import validate_within_root
from geodesy_analysis.insar.baseline import default_baseline_output

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_KEYS = {
    "baseline",
    "master_date",
    "orbit",
    "out_dir",
    "out",
    "title",
    "dpi",
    "figsize",
    "y_top_extra",
    "y_bottom_extra",
    "font_family",
}
_DEFAULTS = {
    "orbit": "",
    "out_dir": "",
    "out": "",
    "title": "",
    "dpi": "300",
    "figsize": "10.5, 6.2",
    "y_top_extra": "50",
    "y_bottom_extra": "0",
    "font_family": "TeX Gyre Heros",
}


@dataclass(frozen=True)
class BaselinePlotCase:
    """One fully resolved, source-neutral baseline plotting request."""

    name: str
    project_root: Path
    baseline: Path
    master_date: int
    orbit: str
    output: Path
    title: str
    dpi: int
    figsize: tuple[float, float]
    y_top_extra: float
    y_bottom_extra: float
    font_family: str


def parse_figsize(text: str) -> tuple[float, float]:
    """Parse a comma- or whitespace-separated positive figure size."""

    parts = text.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("figsize must contain two positive numbers")
    try:
        parsed = tuple(float(value) for value in parts)
    except ValueError as error:
        raise ValueError("figsize must contain two positive numbers") from error
    if any(not math.isfinite(value) or value <= 0 for value in parsed):
        raise ValueError("figsize must contain two positive numbers")
    return parsed  # type: ignore[return-value]


def _unknown(section: configparser.SectionProxy, source: Path) -> None:
    unknown = sorted(set(section) - _KEYS)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _resolve(root: Path, value: str, label: str) -> Path:
    path = Path(value).expanduser()
    return validate_within_root(path if path.is_absolute() else root / path, root, label)


def _master_date(value: str, source: Path) -> int:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{source}: master_date must be YYYYMMDD") from error
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"{source}: master_date must be YYYYMMDD")
    return int(value)


def _positive_integer(value: str, key: str, source: Path) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a positive integer") from error
    if parsed < 1:
        raise ValueError(f"{source}: {key} must be a positive integer")
    return parsed


def _nonnegative_float(value: str, key: str, source: Path) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a non-negative number") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{source}: {key} must be a non-negative number")
    return parsed


def load_baseline_plot_config(path: Path) -> tuple[BaselinePlotCase, ...]:
    """Load ordered standalone baseline plotting cases."""

    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid baseline plot configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    project = parser["project"]
    unknown_project = sorted(set(project) - {"root"})
    if unknown_project:
        raise ValueError(f"{source}: unknown key in [project]: {unknown_project[0]}")
    root_value = project.get("root", "").strip()
    if not root_value:
        raise ValueError(f"{source}: [project] root is required")
    candidate = Path(root_value).expanduser()
    root = (candidate if candidate.is_absolute() else source.parent / candidate).resolve(
        strict=True
    )
    defaults = dict(_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source)
        defaults.update(
            (key, value.strip()) for key, value in parser["defaults"].items()
        )
    cases: list[BaselinePlotCase] = []
    for section_name in parser.sections():
        if section_name in {"project", "defaults"}:
            continue
        if not section_name.startswith("case:"):
            raise ValueError(f"{source}: unsupported section [{section_name}]")
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        missing = [key for key in ("baseline", "master_date") if not values.get(key)]
        if missing:
            raise ValueError(
                f"{source}: [{section_name}] missing keys: {', '.join(missing)}"
            )
        baseline = _resolve(root, values["baseline"], "baseline")
        if not baseline.is_file() or baseline.stat().st_size == 0:
            raise FileNotFoundError(f"baseline file not found or empty: {baseline}")
        out_dir = (
            _resolve(root, values["out_dir"], "plot output directory")
            if values["out_dir"]
            else baseline.parent
        )
        if values["out"]:
            requested = Path(values["out"]).expanduser()
            if requested.is_absolute():
                output = validate_within_root(requested, root, "plot output")
            elif requested.parent == Path("."):
                output = validate_within_root(out_dir / requested, root, "plot output")
            else:
                output = validate_within_root(root / requested, root, "plot output")
        else:
            output = Path(
                default_baseline_output(
                    str(baseline), orbit=values["orbit"], out_dir=str(out_dir)
                )
            ).resolve()
        title = values["title"] or "Perpendicular Baselines History"
        cases.append(
            BaselinePlotCase(
                name=name,
                project_root=root,
                baseline=baseline,
                master_date=_master_date(values["master_date"], source),
                orbit=values["orbit"],
                output=output,
                title=title,
                dpi=_positive_integer(values["dpi"], "dpi", source),
                figsize=parse_figsize(values["figsize"]),
                y_top_extra=_nonnegative_float(
                    values["y_top_extra"], "y_top_extra", source
                ),
                y_bottom_extra=_nonnegative_float(
                    values["y_bottom_extra"], "y_bottom_extra", source
                ),
                font_family=values["font_family"] or "TeX Gyre Heros",
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


def select_baseline_plot_case(
    cases: Sequence[BaselinePlotCase], name: str | None
) -> BaselinePlotCase:
    """Select one plot case, requiring a name only when ambiguous."""

    if name is None:
        if len(cases) != 1:
            raise ValueError("--case is required when configuration has multiple cases")
        return cases[0]
    for case in cases:
        if case.name == name:
            return case
    raise ValueError(f"unknown case: {name}")


__all__ = [
    "BaselinePlotCase",
    "load_baseline_plot_config",
    "parse_figsize",
    "select_baseline_plot_case",
]
