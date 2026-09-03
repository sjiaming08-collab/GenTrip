"""Resolve runtime data files in both source-tree and installed-wheel layouts."""

from __future__ import annotations

from pathlib import Path


def fixture_path(
    filename: str,
    *,
    package_file: str | Path | None = None,
    working_dir: str | Path | None = None,
) -> Path:
    package_root = Path(package_file or __file__).resolve().parents[1]
    runtime_root = Path(working_dir or Path.cwd()).resolve()
    candidates = (
        package_root / "fixtures" / filename,
        runtime_root / "fixtures" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Preserve a deterministic, useful error path for callers that open it.
    return candidates[0]
