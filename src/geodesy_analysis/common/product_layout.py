"""Method-centric product, figure, and log paths for Analysis workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .case_paths import AnalysisCasePaths


@dataclass(frozen=True)
class AnalysisProductLayout:
    """Safe default directories below one declared processing method root."""

    paths: AnalysisCasePaths

    def __post_init__(self) -> None:
        if self.paths.processing_root is None:
            raise ValueError("analysis product layout requires processing_root")

    @property
    def root(self) -> Path:
        assert self.paths.processing_root is not None
        return self.paths.processing_root

    @staticmethod
    def _parts(parts: tuple[str, ...], label: str) -> tuple[str, ...]:
        if not parts:
            raise ValueError(f"{label} requires at least one path component")
        for value in parts:
            part = Path(value)
            if part.is_absolute() or len(part.parts) != 1 or value in {"", ".", ".."}:
                raise ValueError(f"unsafe {label} component: {value!r}")
        return parts

    def product(self, *parts: str) -> Path:
        return self.root.joinpath(*self._parts(parts, "product"))

    def figures(self, *parts: str) -> Path:
        return (self.root / "FIGURES").joinpath(*self._parts(parts, "figure"))

    def logs(self, *parts: str) -> Path:
        return (self.root / "LOG/ANALYSIS").joinpath(*self._parts(parts, "log"))

    @staticmethod
    def _overlap(first: Path, second: Path) -> bool:
        left = first.resolve()
        right = second.resolve()
        return left == right or left in right.parents or right in left.parents

    def require_disjoint(
        self,
        *,
        science: Path,
        figures: Path,
        logs: Path,
        inputs: tuple[Path, ...],
    ) -> None:
        named = (("science", science), ("figures", figures), ("logs", logs))
        protected = named + tuple(("input", value) for value in inputs)
        for index, (left_name, left) in enumerate(protected):
            for right_name, right in protected[index + 1 :]:
                if self._overlap(Path(left), Path(right)):
                    raise ValueError(
                        f"analysis paths overlap: {left_name} {left.resolve()} and "
                        f"{right_name} {right.resolve()}"
                    )

    def serialize(self, path: Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            return resolved.relative_to(self.paths.project_root).as_posix()
        except ValueError:
            return str(resolved)


__all__ = ["AnalysisProductLayout"]
