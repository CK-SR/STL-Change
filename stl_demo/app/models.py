from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


AllowedOp = Literal["scale", "translate", "rotate", "delete", "add", "stretch"]


class PartMeta(BaseModel):
    part_name: str = Field(alias="部件名称")
    file_path: str = Field(alias="文件")
    category: str = Field(default="未知", alias="类别")
    confidence: float = Field(default=0.0, alias="置信度")
    description: str = Field(default="", alias="依据")
    centroid: List[float] = Field(default_factory=list, alias="质心")
    bbox: List[List[float]] = Field(default_factory=list, alias="包围盒")

    model_config = {"populate_by_name": True, "extra": "allow"}


class MetadataDocument(BaseModel):
    model_name: str = Field(default="unknown", alias="模型名称")
    source_file: str = Field(default="", alias="源文件")
    object_type: str = Field(default="", alias="对象类型")
    annotate_method: str = Field(default="", alias="标注方式")
    part_annotations: List[PartMeta] = Field(default_factory=list, alias="部件标注")

    model_config = {"populate_by_name": True, "extra": "allow"}


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


class DemoState(BaseModel):
    discovered_stl_files: List[str] = Field(default_factory=list)

    # Excel / 文本输入
    df: Any | None = None
    schema: Dict[str, Any] = Field(default_factory=dict)
    part_summary: List[Dict[str, Any]] = Field(default_factory=list)
    intelligence_texts: List[str] = Field(default_factory=list)

    # 主流程结果
    change_intent: ChangeIntent = Field(default_factory=ChangeIntent)
    validated_changes: List[ValidationResult] = Field(default_factory=list)
    execution_results: List[SkillExecutionResult] = Field(default_factory=list)

    # Excel 输出
    change_table_path: str = ""
    updated_excel_path: str = ""
    warnings: List[str] = Field(default_factory=list)
    report_paths: Dict[str, str] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}