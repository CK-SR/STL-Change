from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


AllowedOp = Literal["scale", "translate", "rotate", "delete", "add", "stretch"]


class ChangeItem(BaseModel):
    target_part: str
    op: AllowedOp
    params: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ChangeIntent(BaseModel):
    changes: List[ChangeItem] = Field(default_factory=list)


class ValidationResult(BaseModel):
    index: int
    valid: bool = True
    errors: List[str] = Field(default_factory=list)
    change: ChangeItem


class SkillExecutionResult(BaseModel):
    success: bool = False
    output_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    message: str = ""
    target_part: str = ""
    op: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DemoState(BaseModel):
    discovered_stl_files: List[str] = Field(default_factory=list)
    part_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    part_summary: List[Dict[str, Any]] = Field(default_factory=list)
    intelligence_texts: List[str] = Field(default_factory=list)
    change_intent: ChangeIntent = Field(default_factory=ChangeIntent)
    validated_changes: List[ValidationResult] = Field(default_factory=list)
    execution_results: List[SkillExecutionResult] = Field(default_factory=list)
    mesh_repair_reports: List[Dict[str, Any]] = Field(default_factory=list)
    reasonableness_reports: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    report_paths: Dict[str, str] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}