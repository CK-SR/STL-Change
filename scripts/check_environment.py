#!/usr/bin/env python3
"""Check whether the local environment satisfies STL-Change runtime dependencies.

The script intentionally avoids third-party helper packages so it can run before
project dependencies are installed.
"""
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STL_DEMO_DIR = REPO_ROOT / "stl_demo"
REQUIREMENTS_FILE = STL_DEMO_DIR / "requirements.txt"
MIN_PYTHON = (3, 10)

IMPORT_NAME_BY_DIST = {
    "Pillow": "PIL",
}

# Modules used by project code but easy to miss when only testing the main path.
RUNTIME_IMPORTS = {
    "pandas": "pandas",
    "requests": "requests",
    "openpyxl": "openpyxl",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _parse_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value.split("+", 1)[0])
    return tuple(int(part) for part in parts[:4]) or (0,)


def _version_satisfies(installed: str, specifier: str) -> bool:
    specifier = specifier.strip()
    if not specifier:
        return True
    installed_tuple = _parse_version(installed)
    for raw_spec in specifier.split(","):
        spec = raw_spec.strip()
        if not spec:
            continue
        match = re.match(r"(>=|==|>|<=|<)\s*([A-Za-z0-9_.!+\-]+)", spec)
        if not match:
            continue
        op, required = match.groups()
        required_tuple = _parse_version(required)
        if op == ">=" and installed_tuple < required_tuple:
            return False
        if op == ">" and installed_tuple <= required_tuple:
            return False
        if op == "<=" and installed_tuple > required_tuple:
            return False
        if op == "<" and installed_tuple >= required_tuple:
            return False
        if op == "==" and installed_tuple != required_tuple:
            return False
    return True


def _read_requirements() -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        match = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", clean)
        if match:
            dist_name, specifier = match.groups()
            requirements[dist_name] = specifier.strip()
    return requirements


def _check_python_version() -> CheckResult:
    current = sys.version_info[:3]
    ok = current >= MIN_PYTHON
    return CheckResult(
        "python",
        ok,
        f"current={'.'.join(map(str, current))}, required>={'.'.join(map(str, MIN_PYTHON))}",
    )


def _check_distribution(dist_name: str, specifier: str) -> CheckResult:
    import_name = IMPORT_NAME_BY_DIST.get(dist_name, dist_name.replace("-", "_"))
    try:
        module = importlib.import_module(import_name)
    except Exception as exc:  # noqa: BLE001 - report any import-time environment problem.
        return CheckResult(dist_name, False, f"import {import_name!r} failed: {exc}")

    try:
        installed = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        installed = getattr(module, "__version__", "unknown")

    if installed != "unknown" and not _version_satisfies(installed, specifier):
        return CheckResult(dist_name, False, f"installed={installed}, required={specifier}")
    requirement = specifier or "installed"
    return CheckResult(dist_name, True, f"installed={installed}, required={requirement}")


def _check_project_import() -> CheckResult:
    sys.path.insert(0, str(STL_DEMO_DIR))
    try:
        importlib.import_module("app.graph.workflow")
        importlib.import_module("app.services.excel_loader")
        importlib.import_module("app.services.asset_generation_service")
    except Exception as exc:  # noqa: BLE001 - surface the failing import to the user.
        return CheckResult("project imports", False, str(exc))
    return CheckResult("project imports", True, "core app modules imported successfully")


def _check_required_paths() -> list[CheckResult]:
    paths = [
        REQUIREMENTS_FILE,
        STL_DEMO_DIR / "main.py",
        REPO_ROOT / "scripts" / "build_part_constraints_v3.py",
    ]
    return [CheckResult(f"path {path.relative_to(REPO_ROOT)}", path.exists(), "exists" if path.exists() else "missing") for path in paths]


def main() -> int:
    results: list[CheckResult] = [_check_python_version()]

    requirements = _read_requirements()
    for dist_name, specifier in requirements.items():
        results.append(_check_distribution(dist_name, specifier))

    for dist_name, import_name in RUNTIME_IMPORTS.items():
        if dist_name not in requirements:
            results.append(_check_distribution(dist_name, ""))
        else:
            # Keep import aliases documented in one place even if requirements already include the package.
            IMPORT_NAME_BY_DIST.setdefault(dist_name, import_name)

    results.extend(_check_required_paths())
    results.append(_check_project_import())

    failed = [result for result in results if not result.ok]
    for result in results:
        prefix = "PASS" if result.ok else "FAIL"
        print(f"[{prefix}] {result.name}: {result.detail}")

    if failed:
        print("\nEnvironment check failed. Install/update dependencies, for example:")
        print("  python -m pip install -r stl_demo/requirements.txt")
        return 1

    print("\nEnvironment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
