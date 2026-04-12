from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict

from app.models import ChangeIntent, SkillExecutionResult, ValidationResult


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_demo_report(
    report_path: Path,
    intelligence_texts: list[str],
    schema: Dict[str, Any],
    discovered_stl_files: list[str],
    change_intent: ChangeIntent,
    validated_changes: list[ValidationResult],
    execution_results: list[SkillExecutionResult],
    warnings: list[str],
    excel_path: str,
    updated_excel_path: str,
    change_table_path: str,
    final_stl_dir: str,
) -> None:
    success_items = [r for r in execution_results if r.success]
    fail_items = [r for r in execution_results if not r.success]

    lines = [
        "# STL 文本驱动变更 Demo 报告",
        "",
        "## 输入概况",
        f"- 输入 Excel: {excel_path}",
        f"- 扫描到的 STL 数量: {len(discovered_stl_files)}",
        f"- 最终 STL 输出目录: {final_stl_dir}",
        f"- 修改后 Excel: {updated_excel_path}",
        f"- 变更表 Excel: {change_table_path}",
        "",
        "## Excel Schema 识别结果",
        "```json",
        json.dumps(schema, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 情报文本",
    ]
    lines.extend([f"- {t}" for t in intelligence_texts])

    lines += ["", "## 变更意图", "```json", change_intent.model_dump_json(indent=2), "```"]
    lines += [
        "",
        "## 校验结果",
        "```json",
        json.dumps([v.model_dump() for v in validated_changes], ensure_ascii=False, indent=2),
        "```",
    ]
    lines += [
        "",
        "## 执行结果",
        "```json",
        json.dumps([e.model_dump() for e in execution_results], ensure_ascii=False, indent=2),
        "```",
        "",
        f"## 成功项 ({len(success_items)})",
    ]
    lines.extend([f"- {x.op} {x.target_part}: {x.message}" for x in success_items])
    lines += ["", f"## 失败项 ({len(fail_items)})"]
    lines.extend([f"- {x.op} {x.target_part}: {x.message}" for x in fail_items])

    lines += ["", "## Warnings"]
    lines.extend([f"- {w}" for w in warnings] if warnings else ["- 无"])

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")