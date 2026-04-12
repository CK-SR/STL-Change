from __future__ import annotations

from pathlib import Path
from typing import List
import pandas as pd


def load_excel(path: Path, sheet_name: str = "部件数据") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def scan_stl_files(stl_dir: Path) -> List[Path]:
    return sorted(stl_dir.glob("*.stl"))