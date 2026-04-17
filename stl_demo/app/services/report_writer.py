from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict

from app.models import ChangeIntent, SkillExecutionResult, ValidationResult


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _count_reasonableness_status(reasonableness_reports: list[dict]) -> Dict[str, int]:
    stats = {"pass": 0, "warning": 0, "unknown": 0}
    for item in reasonableness_reports:
        status = str(item.get("status", "unknown")).strip().lower()
        if status in stats:
            stats[status] += 1
        else:
            stats["unknown"] += 1
    return stats


def write_demo_report(
    report_path: Path,
    intelligence_texts: list[str],
    schema: Dict[str, Any],
    discovered_stl_files: list[str],
    change_intent: ChangeIntent,
    validated_changes: list[ValidationResult],
    execution_results: list[SkillExecutionResult],
    mesh_repair_reports: list[dict],
    reasonableness_reports: list[dict],
    warnings: list[str],
    excel_path: str,
    updated_excel_path: str,
    change_table_path: str,
    final_stl_dir: str,
) -> None:
    success_items = [r for r in execution_results if r.success]
    fail_items = [r for r in execution_results if not r.success]
    valid_items = [v for v in validated_changes if v.valid]
    invalid_items = [v for v in validated_changes if not v.valid]
    reason_stats = _count_reasonableness_status(reasonableness_reports)

    lines = [
        "# STL 文本驱动变更 Demo 报告",
        "",
        "## 1. 输入概况",
        f"- 输入 Excel: {excel_path}",
        f"- 扫描到的 STL 数量: {len(discovered_stl_files)}",
        f"- 最终 STL 输出目录: {final_stl_dir}",
        f"- 修改后 Excel: {updated_excel_path}",
        f"- 变更表 Excel: {change_table_path}",
        "",
        "## 2. 情报文本",
    ]
    lines.extend([f"- {t}" for t in intelligence_texts] if intelligence_texts else ["- 无"])

    lines += [
        "",
        "## 3. 约束来源",
        "```json",
        json.dumps(schema, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 4. 原始变更意图",
        "```json",
        change_intent.model_dump_json(indent=2),
        "```",
        "",
        f"## 5. 校验结果概览",
        f"- 有效变更数: {len(valid_items)}",
        f"- 无效变更数: {len(invalid_items)}",
        "",
        "### 5.1 详细校验结果",
        "```json",
        json.dumps([v.model_dump() for v in validated_changes], ensure_ascii=False, indent=2),
        "```",
        "",
        f"## 6. 执行结果概览",
        f"- 成功执行数: {len(success_items)}",
        f"- 失败执行数: {len(fail_items)}",
        "",
        "### 6.1 成功项",
    ]

    lines.extend(
        [f"- {x.op} {x.target_part}: {x.message}" for x in success_items]
        if success_items
        else ["- 无"]
    )

    lines += [
        "",
        "### 6.2 失败项",
    ]
    lines.extend(
        [f"- {x.op} {x.target_part}: {x.message}" for x in fail_items]
        if fail_items
        else ["- 无"]
    )

    lines += [
        "",
        "### 6.3 执行结果明细",
        "```json",
        json.dumps([e.model_dump() for e in execution_results], ensure_ascii=False, indent=2),
        "```",
        "",
        f"## 7. Mesh Repair 结果",
        f"- repair 记录数: {len(mesh_repair_reports)}",
        "```json",
        json.dumps(mesh_repair_reports, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 8. 合理性检查结果",
        f"- pass: {reason_stats['pass']}",
        f"- warning: {reason_stats['warning']}",
        f"- unknown: {reason_stats['unknown']}",
        "",
        "```json",
        json.dumps(reasonableness_reports, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 9. 最终结论",
    ]

    if fail_items:
        conclusion = "本次变更流程已执行，但存在执行失败项，需优先修正失败操作后再用于正式展示。"
    elif reason_stats["warning"] > 0:
        conclusion = "本次变更流程已完成，但合理性检查给出 warning，建议结合碰撞/间隙/对称性结果人工复核。"
    else:
        conclusion = "本次变更流程顺利完成，且自动修复与合理性检查未发现明显异常，可作为当前阶段 demo 展示结果。"

    lines.append(f"- {conclusion}")

    lines += [
        "",
        "## 10. 全局 Warnings",
    ]
    lines.extend([f"- {w}" for w in warnings] if warnings else ["- 无"])

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")