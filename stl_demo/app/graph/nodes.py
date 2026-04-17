from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.llm.mock_client import MockLLMClient
from app.llm.openai_compatible import OpenAICompatibleLLMClient
from app.models import DemoState
from app.services.intent_generator import generate_change_intent
from app.services.intelligence_generator import generate_mock_intelligence
from app.services.part_constraints_loader import (
    build_existing_parts_set_from_constraints,
    build_part_to_file_map_from_constraints,
    load_part_constraints,
)
from app.services.excel_loader import scan_stl_files
from app.services.part_summary_builder import build_part_summary_from_constraints
from app.services.stl_bundle_preparer import prepare_full_stl_bundle
from app.services.report_writer import write_demo_report, write_json
from app.services.validator import validate_change_intent
from app.skills.dispatcher import dispatch_change

from app.services.mesh_repair_service import repair_mesh_file, record_to_dict
from app.services.reasonableness_checker import check_reasonableness, report_to_dict

logger = logging.getLogger(__name__)


def load_inputs(state: DemoState) -> DemoState:
    part_constraints = load_part_constraints(settings.part_constraints_path)
    stl_files = scan_stl_files(settings.stl_dir)

    state.part_constraints = part_constraints
    state.discovered_stl_files = [str(p) for p in stl_files]

    if not stl_files:
        state.warnings.append(f"No STL files found under {settings.stl_dir}")

    logger.info(
        "Loaded part_constraints=%d and stl_files=%d",
        len(part_constraints),
        len(stl_files),
    )
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
    state.part_summary = build_part_summary_from_constraints(state.part_constraints)
    return state


def generate_change_intent_node(state: DemoState) -> DemoState:
    if settings.llm_mode == "openai":
        llm = OpenAICompatibleLLMClient(
            settings.base_url,
            settings.api_key,
            settings.model_name,
        )
    else:
        llm = MockLLMClient()

    state.change_intent = generate_change_intent(
        llm,
        state.intelligence_texts,
        state.part_summary,
    )
    return state


def validate_change_intent_node(state: DemoState) -> DemoState:
    existing_parts = build_existing_parts_set_from_constraints(state.part_constraints)
    existing_parts.update(Path(s).name for s in state.discovered_stl_files)

    state.validated_changes = validate_change_intent(
        state.change_intent,
        existing_parts,
        state.part_constraints,
    )

    for item in state.validated_changes:
        if not item.valid:
            state.warnings.append(f"Change #{item.index} invalid: {'; '.join(item.errors)}")

    return state


def prepare_stl_bundle_node(state: DemoState) -> DemoState:
    copied = prepare_full_stl_bundle(settings.stl_dir, settings.final_stl_dir)
    logger.info("Prepared final STL bundle, copied %d files", len(copied))
    return state


def apply_skills(state: DemoState) -> DemoState:
    part_to_file = build_part_to_file_map_from_constraints(
        state.part_constraints,
        settings.final_stl_dir,
    )

    for p in settings.final_stl_dir.glob("*.stl"):
        part_to_file[p.name] = p

    for vr in state.validated_changes:
        if not vr.valid:
            continue

        old_input_path = part_to_file.get(vr.change.target_part)

        if vr.change.target_part not in part_to_file and vr.change.op != "add":
            state.execution_results.append(
                dispatch_change(vr.change, part_to_file, settings.final_stl_dir)
            )
            continue

        result = dispatch_change(vr.change, part_to_file, settings.final_stl_dir)

        # Day3: 统一执行后 mesh repair
        if result.success and result.output_files:
            repaired_files = []
            for output_file in result.output_files:
                try:
                    repair_record = repair_mesh_file(output_file, overwrite=True, enable_light_remesh=False)
                    state.mesh_repair_reports.append(record_to_dict(repair_record))
                    repaired_files.append(repair_record.output_path)

                    if repair_record.actions:
                        result.warnings.append(
                            f"mesh_repair_actions={','.join(repair_record.actions)}"
                        )
                    if repair_record.warnings:
                        result.warnings.extend(
                            [f"mesh_repair_warning={w}" for w in repair_record.warnings]
                        )
                except Exception as exc:
                    result.warnings.append(f"mesh_repair_failed={exc}")
                    repaired_files.append(output_file)

            result.output_files = repaired_files

        state.execution_results.append(result)

        if vr.change.op == "add" and result.success and result.output_files:
            new_file = Path(result.output_files[0])
            part_to_file[new_file.name] = new_file

        if vr.change.op in {"translate", "rotate", "stretch", "scale"} and result.success and result.output_files:
            new_file = Path(result.output_files[0])
            part_to_file[vr.change.target_part] = new_file

        # Day4: 编辑后合理性检查
        if (
            result.success
            and result.output_files
            and old_input_path is not None
            and Path(old_input_path).exists()
        ):
            for output_file in result.output_files:
                try:
                    reason_report = check_reasonableness(
                        part_id=vr.change.target_part,
                        op=vr.change.op,
                        input_path=old_input_path,
                        output_path=output_file,
                        part_to_file=part_to_file,
                        part_constraints=state.part_constraints,
                    )
                    state.reasonableness_reports.append(report_to_dict(reason_report))

                    if reason_report.status != "pass":
                        result.warnings.append(
                            f"reasonableness_status={reason_report.status}"
                        )
                except Exception as exc:
                    result.warnings.append(f"reasonableness_check_failed={exc}")

        if result.warnings:
            state.warnings.extend(result.warnings)

    return state


def export_report(state: DemoState) -> DemoState:
    ci_path = settings.reports_dir / "change_intent.json"
    vc_path = settings.reports_dir / "validated_changes.json"
    er_path = settings.reports_dir / "execution_results.json"
    mr_path = settings.reports_dir / "mesh_repair_report.json"
    rr_path = settings.reports_dir / "reasonableness_report.json"
    md_path = settings.reports_dir / "demo_report.md"

    write_json(ci_path, state.change_intent.model_dump())
    write_json(vc_path, [x.model_dump() for x in state.validated_changes])
    write_json(er_path, [x.model_dump() for x in state.execution_results])
    write_json(mr_path, state.mesh_repair_reports)
    write_json(rr_path, state.reasonableness_reports)

    write_demo_report(
        report_path=md_path,
        intelligence_texts=state.intelligence_texts,
        schema={"source": "part_constraints.json"},
        discovered_stl_files=state.discovered_stl_files,
        change_intent=state.change_intent,
        validated_changes=state.validated_changes,
        execution_results=state.execution_results,
        mesh_repair_reports=state.mesh_repair_reports,
        reasonableness_reports=state.reasonableness_reports,
        warnings=state.warnings,
        excel_path="N/A (minimal flow without excel)",
        updated_excel_path="N/A",
        change_table_path="N/A",
        final_stl_dir=str(settings.final_stl_dir),
    )

    state.report_paths = {
        "change_intent": str(ci_path),
        "validated_changes": str(vc_path),
        "execution_results": str(er_path),
        "mesh_repair_report": str(mr_path),
        "reasonableness_report": str(rr_path),
        "demo_report": str(md_path),
        "final_stl_dir": str(settings.final_stl_dir),
    }
    return state