"""Project-confined path validation for Analysis workflows."""

from __future__ import annotations

from pathlib import Path


def validate_within_root(path: Path, root: Path, label: str) -> Path:
    """Resolve *path* and reject values outside the resolved project root."""

    project_root = Path(root).expanduser().resolve()
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise ValueError(f"{label} path must stay inside project root: {resolved}") from error
    return resolved


__all__ = ["validate_within_root"]
