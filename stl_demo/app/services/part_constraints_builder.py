from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def build_part_constraints_via_script(
    *,
    script_path: Path,
    csv_dir: Path,
    stl_root: Path,
    out_dir: Path,
    timeout_sec: int = 1800,
) -> Path:
    env = os.environ.copy()
    env["PART_CONSTRAINTS_CSV_DIR"] = str(csv_dir)
    env["PART_CONSTRAINTS_STL_ROOT"] = str(stl_root)
    env["PART_CONSTRAINTS_OUT_DIR"] = str(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "build_part_constraints_v3.py failed\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )

    output_path = out_dir / "part_constraints.json"
    if not output_path.exists():
        raise FileNotFoundError(f"part_constraints.json not generated: {output_path}")

    return output_path
