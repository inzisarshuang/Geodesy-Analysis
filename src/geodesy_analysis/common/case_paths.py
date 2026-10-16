"""Formal project/case path boundaries for Analysis workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_CASE_COMPONENT = re.compile(r"[A-Z0-9_]+")


@dataclass(frozen=True)
class AnalysisCasePaths:
    """Resolved identity and filesystem boundaries for one Analysis case."""

    label: str
    case_id: str
    project_root: Path
    case_root: Path


def _require_within(path: Path, root: Path, label: str, root_label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} path must stay inside {root_label}: {resolved}") from error
    return resolved


def _resolve_declared_path(project_root: Path, value: str | Path, label: str) -> Path:
    raw = str(value)
    if not raw:
        raise ValueError(f"{label} path must not be empty")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if "\\" in raw or raw.startswith("~"):
            raise ValueError(f"{label} must be a POSIX project-relative path")
        components = raw.split("/")
        if any(component in {"", ".", ".."} for component in components):
            raise ValueError(f"{label} must not contain empty, dot, or parent components")
        candidate = project_root.joinpath(*components)
    return candidate.resolve()


def bind_analysis_case(
    project_root: str | Path, label: str, case_root: str | Path
) -> AnalysisCasePaths:
    """Bind a formal two-component case without creating filesystem content."""

    project = Path(project_root).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"project root must be an existing directory: {project}")

    raw_case = str(case_root)
    if Path(raw_case).is_absolute() or "\\" in raw_case or raw_case.startswith("~"):
        raise ValueError("case root must be a relative POSIX case identifier")
    components = raw_case.split("/")
    if len(components) != 2 or any(
        not component or _CASE_COMPONENT.fullmatch(component) is None
        for component in components
    ):
        raise ValueError(
            "case root must contain exactly two uppercase POSIX components"
        )

    case_id = "/".join(components)
    resolved_case = _require_within(
        project.joinpath(*components), project, "case root", "project root"
    )
    return AnalysisCasePaths(
        label=label,
        case_id=case_id,
        project_root=project,
        case_root=resolved_case,
    )


def resolve_project_input(
    paths: AnalysisCasePaths, value: str | Path, *, must_exist: bool = True
) -> Path:
    """Resolve an input anywhere inside the research project."""

    resolved = _require_within(
        _resolve_declared_path(paths.project_root, value, "project input"),
        paths.project_root,
        "project input",
        "project root",
    )
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"project input does not exist: {resolved}")
    return resolved


def resolve_case_input(
    paths: AnalysisCasePaths, value: str | Path, *, must_exist: bool = True
) -> Path:
    """Resolve an input and require it to belong to the bound case."""

    resolved = _require_within(
        _resolve_declared_path(paths.project_root, value, "case input"),
        paths.case_root,
        "case input",
        "case root",
    )
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"case input does not exist: {resolved}")
    return resolved


def resolve_case_output(paths: AnalysisCasePaths, value: str | Path) -> Path:
    """Resolve a current or future output and require case containment."""

    return _require_within(
        _resolve_declared_path(paths.project_root, value, "case output"),
        paths.case_root,
        "case output",
        "case root",
    )


__all__ = [
    "AnalysisCasePaths",
    "bind_analysis_case",
    "resolve_case_input",
    "resolve_case_output",
    "resolve_project_input",
]
