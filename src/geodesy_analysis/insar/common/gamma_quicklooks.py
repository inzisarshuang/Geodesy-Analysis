"""Pure GAMMA DISP command contracts for stage-owned QC quicklooks."""

from __future__ import annotations

from pathlib import Path


def _background_free_command(
    data: Path, width: int, output: Path, color_map: str
) -> tuple[str, ...]:
    return (
        "rasdt_pwr",
        str(data),
        "-",
        str(width),
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "2",
        color_map,
        str(output),
    )


def mli_quicklook_command(
    data: Path, width: int, output: Path
) -> tuple[str, ...]:
    """Build the legacy grayscale MLI display command."""

    return (
        "raspwr",
        str(data),
        str(width),
        "1",
        "0",
        "1",
        "1",
        "1.",
        ".35",
        "gray.cm",
        str(output),
    )


def wrapped_phase_quicklook_command(
    data: Path,
    width: int,
    output: Path,
    *,
    nonlocal_mode: bool = False,
    line_start: str = "-",
) -> tuple[str, ...]:
    """Build the legacy wrapped-phase command for GAMMA or NL-InSAR."""

    if nonlocal_mode:
        return _background_free_command(data, width, output, "rmg.cm")
    if line_start not in {"-", "0"}:
        raise ValueError("line_start must be '-' or '0'")
    return (
        "rasmph",
        str(data),
        str(width),
        "1",
        line_start,
        "1",
        "1",
        "1",
        ".35",
        "rmg.cm",
        str(output),
    )


def coherence_quicklook_command(
    data: Path,
    width: int,
    output: Path,
    *,
    background: Path | None,
) -> tuple[str, ...]:
    """Build a coherence command with optional average-MLI background."""

    if background is None:
        return _background_free_command(data, width, output, "cc.cm")
    return (
        "rasdt_pwr",
        str(data),
        str(background),
        str(width),
        "-",
        "-",
        "-",
        "-",
        "0",
        "1",
        "0",
        "cc.cm",
        str(output),
    )


def unwrapped_phase_quicklook_command(
    data: Path, width: int, output: Path
) -> tuple[str, ...]:
    """Build the legacy background-free unwrapped-phase command."""

    return _background_free_command(data, width, output, "rmg.cm")


def require_nonempty_quicklook(path: Path, label: str) -> Path:
    """Require a GAMMA DISP invocation to have written a nonempty file."""

    if not path.is_file():
        raise RuntimeError(f"{label} quicklook is missing: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"{label} quicklook is empty: {path}")
    return path


__all__ = [
    "coherence_quicklook_command",
    "mli_quicklook_command",
    "require_nonempty_quicklook",
    "unwrapped_phase_quicklook_command",
    "wrapped_phase_quicklook_command",
]
