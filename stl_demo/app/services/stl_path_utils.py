from __future__ import annotations

from pathlib import Path


_TEMP_STL_PREFIXES = (".__tmp__", "__tmp__", "tmp_")


def is_temp_stl_path(path: str | Path) -> bool:
    """Return True for pipeline scratch STL files that must not be treated as final parts."""
    name = Path(path).name
    return name.lower().endswith(".stl") and name.startswith(_TEMP_STL_PREFIXES)
