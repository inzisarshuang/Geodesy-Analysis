"""Read-only classification of expensive Analysis result directories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ReuseState(str, Enum):
    ABSENT = "absent"
    COMPLETE = "complete"
    FIGURES_MISSING = "figures_missing"
    INCOMPLETE = "incomplete"
    CORRUPT = "corrupt"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class ReuseDecision:
    state: ReuseState
    output_dir: Path
    reason: str
    manifest: dict[str, Any] | None = None

    @property
    def science_reusable(self) -> bool:
        return self.state in {ReuseState.COMPLETE, ReuseState.FIGURES_MISSING}

    @property
    def guidance(self) -> str:
        if self.state in {
            ReuseState.INCOMPLETE,
            ReuseState.CORRUPT,
            ReuseState.MISMATCH,
        }:
            return (
                f"{self.reason}. Delete {self.output_dir} after inspection or choose "
                "a different output_dir; existing science was not modified"
            )
        return self.reason


def classify_analysis_output(
    output_dir: str | Path,
    manifest_name: str,
    expected_signature: str,
) -> ReuseDecision:
    """Classify science and figure completeness without mutating either tree."""

    output = Path(output_dir).expanduser()
    name = Path(manifest_name)
    if name.is_absolute() or len(name.parts) != 1 or manifest_name in {"", ".", ".."}:
        raise ValueError("manifest_name must be one safe filename")
    if output.is_symlink():
        return ReuseDecision(ReuseState.MISMATCH, output, "output is a symbolic link")
    if not output.exists():
        return ReuseDecision(ReuseState.ABSENT, output, "output does not exist")
    if not output.is_dir():
        return ReuseDecision(ReuseState.INCOMPLETE, output, "output is not a directory")
    manifest_path = output / manifest_name
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ReuseDecision(
            ReuseState.INCOMPLETE, output, "completion manifest is missing"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return ReuseDecision(
            ReuseState.CORRUPT, output, f"completion manifest is corrupt: {error}"
        )
    if not isinstance(payload, dict):
        return ReuseDecision(
            ReuseState.CORRUPT, output, "completion manifest is not an object"
        )
    if payload.get("status") != "complete":
        return ReuseDecision(
            ReuseState.INCOMPLETE, output, "manifest does not declare status=complete", payload
        )
    if payload.get("input_signature") != expected_signature:
        return ReuseDecision(
            ReuseState.MISMATCH, output, "input/config signature changed", payload
        )
    products = payload.get("required_products")
    if not isinstance(products, list) or not products:
        return ReuseDecision(
            ReuseState.INCOMPLETE, output, "required product inventory is missing", payload
        )
    for value in products:
        if not isinstance(value, str):
            return ReuseDecision(
                ReuseState.CORRUPT, output, "required product path is invalid", payload
            )
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            return ReuseDecision(
                ReuseState.CORRUPT, output, "required product escapes output", payload
            )
        product = output / relative
        if product.is_symlink() or not product.is_file() or product.stat().st_size < 1:
            return ReuseDecision(
                ReuseState.INCOMPLETE,
                output,
                f"required science product is missing or empty: {value}",
                payload,
            )
    figures = payload.get("figures", [])
    if not isinstance(figures, list):
        return ReuseDecision(
            ReuseState.CORRUPT, output, "figure inventory is invalid", payload
        )
    for value in figures:
        if not isinstance(value, str):
            return ReuseDecision(
                ReuseState.CORRUPT, output, "figure path is invalid", payload
            )
        figure = Path(value).expanduser()
        if not figure.is_absolute():
            figure = output / figure
        if not figure.is_file() or figure.stat().st_size < 1:
            return ReuseDecision(
                ReuseState.FIGURES_MISSING,
                output,
                f"science is complete but a figure is missing: {figure}",
                payload,
            )
    return ReuseDecision(
        ReuseState.COMPLETE, output, "science and figures are complete", payload
    )


__all__ = ["ReuseDecision", "ReuseState", "classify_analysis_output"]
