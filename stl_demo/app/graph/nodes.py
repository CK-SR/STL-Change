from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.llm.mock_client import MockLLMClient
from app.llm.openai_compatible import OpenAICompatibleLLMClient
from app.models import DemoState
from app.services.intent_generator import generate_change_intent
from app.services.intelligence_generator import generate_mock_intelligence
from app.services.excel_loader import load_excel, scan_stl_files
from app.services.schema_analyzer import analyze_excel_schema
from app.services.part_summary_builder import build_part_summary_from_excel
from app.services.excel_indexer import build_existing_parts_set_from_excel, build_part_to_file_map_from_excel
from app.services.excel_change_writer import build_change_table_from_intent, apply_change_intent_to_excel
from app.services.stl_bundle_preparer import prepare_full_stl_bundle
from app.services.report_writer import write_demo_report, write_json
from app.services.validator import validate_change_intent
from app.skills.dispatcher import dispatch_change

logger = logging.getLogger(__name__)


def load_inputs(state: DemoState) -> DemoState:
    df = load_excel(settings.excel_path, sheet_name="部件数据")
    schema = analyze_excel_schema(df)
    stl_files = scan_stl_files(settings.stl_dir)

    state.df = df
    state.schema = schema
    state.discovered_stl_files = [str(p) for p in stl_files]

    if not stl_files:
        state.warnings.append(f"No STL files found under {settings.stl_dir}")

    logger.info("Loaded excel and %d STL files", len(stl_files))
    return state


def generate_intelligence(state: DemoState) -> DemoState:
    if settings.text_path.exists():
        text = settings.text_path.read_text(encoding="utf-8").strip()
        state.intelligence_texts = [text] if text else []
    else:
        state.intelligence_texts = generate_mock_intelligence()

    if not state.intelligence_texts:
        state.intelligence_texts = generate_mock_intelligence()

    return state


def build_part_summary_node(state: DemoState) -> DemoState:
    assert state.df is not None
    state.part_summary = build_part_summary_from_excel(state.df, state.schema)
    return state


def generate_change_intent_node(state: DemoState) -> DemoState:
    if settings.llm_mode == "openai":
        llm = OpenAICompatibleLLMClient(settings.base_url, settings.api_key, settings.model_name)
    else:
        llm = MockLLMClient()

    state.change_intent = generate_change_intent(llm, state.intelligence_texts, state.part_summary)
    return state


def validate_change_intent_node(state: DemoState) -> DemoState:
    assert state.df is not None

    existing_parts = build_existing_parts_set_from_excel(state.df, state.schema)
    existing_parts.update(Path(s).name for s in state.discovered_stl_files)

    state.validated_changes = validate_change_intent(state.change_intent, existing_parts)

    for item in state.validated_changes:
        if not item.valid:
            state.warnings.append(f"Change #{item.index} invalid: {'; '.join(item.errors)}")

    return state


def prepare_stl_bundle_node(state: DemoState) -> DemoState:
    copied = prepare_full_stl_bundle(settings.stl_dir, settings.final_stl_dir)
    logger.info("Prepared final STL bundle, copied %d files", len(copied))
    return state


def apply_skills(state: DemoState) -> DemoState:
    assert state.df is not None

    part_to_file = build_part_to_file_map_from_excel(state.df, state.schema, settings.final_stl_dir)

    # 保险：把输出目录中已有 STL 也补进去
    for p in settings.final_stl_dir.glob("*.stl"):
        part_to_file[p.name] = p

    for vr in state.validated_changes:
        if not vr.valid:
            continue

        if vr.change.target_part not in part_to_file and vr.change.op != "add":
            state.execution_results.append(
                dispatch_change(vr.change, part_to_file, settings.final_stl_dir)
            )
            continue

        result = dispatch_change(vr.change, part_to_file, settings.final_stl_dir)
        state.execution_results.append(result)

        # add 之后把新文件补进 map，方便后续链式操作
        if vr.change.op == "add" and result.success and result.output_files:
            new_file = Path(result.output_files[0])
            part_to_file[new_file.name] = new_file

        if result.warnings:
            state.warnings.extend(result.warnings)

    return state


def write_excel_outputs_node(state: DemoState) -> DemoState:
    assert state.df is not None

    change_table = build_change_table_from_intent(state.change_intent, state.df, state.schema)
    updated_df = apply_change_intent_to_excel(state.change_intent, state.df, state.schema)

    settings.change_table_path.parent.mkdir(parents=True, exist_ok=True)
    change_table.to_excel(settings.change_table_path, index=False)
    updated_df.to_excel(settings.updated_excel_path, index=False)

    state.change_table_path = str(settings.change_table_path)
    state.updated_excel_path = str(settings.updated_excel_path)

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
        report_path=md_path,
        intelligence_texts=state.intelligence_texts,
        schema=state.schema,
        discovered_stl_files=state.discovered_stl_files,
        change_intent=state.change_intent,
        validated_changes=state.validated_changes,
        execution_results=state.execution_results,
        warnings=state.warnings,
        excel_path=str(settings.excel_path),
        updated_excel_path=state.updated_excel_path,
        change_table_path=state.change_table_path,
        final_stl_dir=str(settings.final_stl_dir),
    )

    state.report_paths = {
        "change_intent": str(ci_path),
        "validated_changes": str(vc_path),
        "execution_results": str(er_path),
        "demo_report": str(md_path),
        "change_table": state.change_table_path,
        "updated_excel": state.updated_excel_path,
        "final_stl_dir": str(settings.final_stl_dir),
    }
    return state