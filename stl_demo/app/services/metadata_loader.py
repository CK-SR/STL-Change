from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.models import MetadataDocument
from app.utils.json_utils import load_json


def load_metadata(path: Path) -> MetadataDocument:
    data = load_json(path)
    return MetadataDocument.model_validate(data)


def scan_stl_files(stl_dir: Path) -> List[Path]:
    return sorted(stl_dir.glob("*.stl"))


def build_filename_index(metadata: MetadataDocument) -> Dict[str, str]:
    return {part.part_name: part.file_path for part in metadata.part_annotations}


def build_part_summary(metadata: MetadataDocument) -> List[dict]:
    return [
        {
            "part_name": part.part_name,
            "file_path": part.file_path,
            "category": part.category,
            "confidence": part.confidence,
            "description": part.description,
            "centroid": part.centroid,
            "bbox": part.bbox,
        }
        for part in metadata.part_annotations
    ]
