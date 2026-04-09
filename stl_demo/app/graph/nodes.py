from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.llm.mock_client import MockLLMClient
from app.llm.openai_compatible import OpenAICompatibleLLMClient
from app.models import DemoState
from app.services.intent_generator import generate_change_intent
from app.services.intelligence_generator import generate_mock_intelligence
from app.services.metadata_loader import build_filename_index, build_part_summary, load_metadata, scan_stl_files
from app.services.report_writer import write_demo_report, write_json
from app.services.validator import validate_change_intent
from app.skills.dispatcher import dispatch_change

logger = logging.getLogger(__name__)


def load_inputs(state: DemoState) -> DemoState:
    metadata = load_metadata(settings.metadata_path)
    stl_files = scan_stl_files(settings.stl_dir)
    state.metadata = metadata
    state.discovered_stl_files = [str(p) for p in stl_files]
    if not stl_files:
        state.warnings.append(f"No STL files found under {settings.stl_dir}")
    logger.info("Loaded metadata and %d STL files", len(stl_files))
    return state


def generate_intelligence(state: DemoState) -> DemoState:
    state.intelligence_texts = generate_mock_intelligence()
    return state


def build_part_summary_node(state: DemoState) -> DemoState:
    state.part_summary = build_part_summary(state.metadata)
    return state


def generate_change_intent_node(state: DemoState) -> DemoState:
    if settings.llm_mode == "openai":
        llm = OpenAICompatibleLLMClient(settings.base_url, settings.api_key, settings.model_name)
    else:
        llm = MockLLMClient()

    state.change_intent = generate_change_intent(llm, state.intelligence_texts, state.part_summary)
    return state


def validate_change_intent_node(state: DemoState) -> DemoState:
    assert state.metadata is not None
    existing_parts = set(build_filename_index(state.metadata).keys())
    existing_parts.update(Path(s).name for s in state.discovered_stl_files)
    state.validated_changes = validate_change_intent(state.change_intent, existing_parts)
    for item in state.validated_changes:
        if not item.valid:
            state.warnings.append(f"Change #{item.index} invalid: {'; '.join(item.errors)}")
    return state


def apply_skills(state: DemoState) -> DemoState:
    assert state.metadata is not None
    part_index = build_filename_index(state.metadata)
    part_to_file = {
        part_name: (settings.project_root / rel_path)
        if not Path(rel_path).is_absolute()
        else Path(rel_path)
        for part_name, rel_path in part_index.items()
    }

    for vr in state.validated_changes:
        if not vr.valid:
            continue
        result = dispatch_change(vr.change, part_to_file, settings.modified_stl_dir)
        state.execution_results.append(result)
        if result.warnings:
            state.warnings.extend(result.warnings)
    return state


def export_report(state: DemoState) -> DemoState:
    ci_path = settings.reports_dir / "change_intent.json"
    vc_path = settings.reports_dir / "validated_changes.json"
    er_path = settings.reports_dir / "execution_results.json"
    md_path = settings.reports_dir / "demo_report.md"

    write_json(ci_path, state.change_intent.model_dump())
    write_json(vc_path, [x.model_dump() for x in state.validated_changes])
    write_json(er_path, [x.model_dump() for x in state.execution_results])
    write_demo_report(
        md_path,
        state.metadata,
        state.intelligence_texts,
        state.change_intent,
        state.validated_changes,
        state.execution_results,
        state.warnings,
    )
    state.report_paths = {
        "change_intent": str(ci_path),
        "validated_changes": str(vc_path),
        "execution_results": str(er_path),
        "demo_report": str(md_path),
    }
    return state
