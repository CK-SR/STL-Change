from __future__ import annotations

import logging
import os
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
from app.services.part_constraints_builder import build_part_constraints_via_script
from app.services.excel_loader import scan_stl_files
from app.services.part_summary_builder import build_part_summary_from_constraints
from app.services.stl_bundle_preparer import prepare_full_stl_bundle
from app.services.report_writer import write_demo_report, write_json
from app.services.validator import validate_change_intent
from app.skills.dispatcher import dispatch_change

from app.services.mesh_repair_service import repair_mesh_file, record_to_dict
from app.services.reasonableness_checker import check_reasonableness, report_to_dict

logger = logging.getLogger(__name__)


def _canonical_part_output_path(output_dir: Path, part_name: str) -> Path:
    stem = Path(part_name).stem
    return output_dir / f"{stem}.stl"


def _promote_to_final_snapshot(temp_path: Path, final_path: Path) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)

    if temp_path.resolve() == final_path.resolve():
        return final_path

    if final_path.exists():
        final_path.unlink()

    os.replace(str(temp_path), str(final_path))
    return final_path


def load_inputs(state: DemoState) -> DemoState:
    generated_constraints_path = build_part_constraints_via_script(
        script_path=settings.part_constraints_builder_script,
        csv_dir=settings.part_constraints_csv_dir,
        stl_root=settings.part_constraints_stl_root,
        out_dir=settings.part_constraints_out_dir,
    )
    settings.part_constraints_path = generated_constraints_path

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

        target = vr.change.target_part
        op = vr.change.op

        if target not in part_to_file and op != "add":
            state.execution_results.append(
                dispatch_change(vr.change, part_to_file, settings.final_stl_dir)
            )
            continue

        result = dispatch_change(vr.change, part_to_file, settings.final_stl_dir)

        if op == "delete":
            if result.success:
                part_to_file.pop(target, None)
            state.execution_results.append(result)
            if result.warnings:
                state.warnings.extend(result.warnings)
            continue

        affected_parts = result.metadata.get("affected_parts", []) if result.metadata else []

        final_files = []
        for item in affected_parts:
            part_id = str(item.get("part_id", "")).strip()
            input_path_str = str(item.get("input_path", "")).strip()
            temp_output_str = str(item.get("temp_output_path", "")).strip()

            if not part_id or not temp_output_str:
                continue

            temp_output = Path(temp_output_str)
            if not temp_output.exists():
                result.warnings.append(f"missing_temp_output[{part_id}]={temp_output}")
                continue

            repaired_output = temp_output
            try:
                repair_record = repair_mesh_file(
                    temp_output,
                    overwrite=True,
                    enable_light_remesh=False,
                )
                state.mesh_repair_reports.append(record_to_dict(repair_record))
                repaired_output = Path(repair_record.output_path)

                if repair_record.actions:
                    result.warnings.append(
                        f"mesh_repair_actions[{part_id}]={','.join(repair_record.actions)}"
                    )
                if repair_record.warnings:
                    result.warnings.extend(
                        [f"mesh_repair_warning[{part_id}]={w}" for w in repair_record.warnings]
                    )
            except Exception as exc:
                result.warnings.append(f"mesh_repair_failed[{part_id}]={exc}")

            input_path = Path(input_path_str) if input_path_str else None
            if input_path is not None and input_path.exists():
                try:
                    reason_report = check_reasonableness(
                        part_id=part_id,
                        op=op,
                        input_path=input_path,
                        output_path=repaired_output,
                        part_to_file=part_to_file,
                        part_constraints=state.part_constraints,
                    )
                    state.reasonableness_reports.append(report_to_dict(reason_report))

                    if reason_report.status != "pass":
                        result.warnings.append(
                            f"reasonableness_status[{part_id}]={reason_report.status}"
                        )
                except Exception as exc:
                    result.warnings.append(f"reasonableness_check_failed[{part_id}]={exc}")
            else:
                result.warnings.append(f"reasonableness_skipped[{part_id}]=no_input_mesh")

            final_output_path = _canonical_part_output_path(settings.final_stl_dir, part_id)
            promoted_path = _promote_to_final_snapshot(repaired_output, final_output_path)

            final_files.append(str(promoted_path))
            part_to_file[part_id] = promoted_path
            part_to_file[promoted_path.name] = promoted_path

        if final_files:
            result.output_files = final_files

        state.execution_results.append(result)

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
