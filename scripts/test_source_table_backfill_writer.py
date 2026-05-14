from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

import pandas as pd
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "stl_demo"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.models import SkillExecutionResult
from app.services.source_table_backfill_writer import export_source_table_syncs


class SourceTableSyncWriterTest(unittest.TestCase):
    def test_syncs_only_successful_execution_results_to_builder_source_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_dir = tmp_path / "csv"
            output_dir = tmp_path / "out"
            stl_dir = tmp_path / "stl"
            csv_dir.mkdir()
            stl_dir.mkdir()

            existing_stl = stl_dir / "BJ0002.stl"
            added_stl = stl_dir / "BJ0003.stl"
            trimesh.creation.box(extents=(10.0, 20.0, 30.0)).export(existing_stl)
            trimesh.creation.box(extents=(5.0, 6.0, 7.0)).export(added_stl)

            pd.DataFrame([
                {"目标ID": "T001", "目标名称": "目标A"}
            ]).to_csv(csv_dir / "2.1目标基本信息数据.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame([
                {
                    "目标ID": "T001",
                    "部件ID": "BJ0001",
                    "部件名称": "车身",
                    "父部件ID": "",
                    "父部件名称": "",
                    "部件类别": "主体",
                    "长度": "",
                    "宽度": "",
                    "高度": "",
                    "位置X": "",
                    "位置Y": "",
                    "位置Z": "",
                    "备注": "",
                },
                {
                    "目标ID": "T001",
                    "部件ID": "BJ0002",
                    "部件名称": "传感器",
                    "父部件ID": "BJ0001",
                    "父部件名称": "",
                    "部件类别": "设备",
                    "长度": "",
                    "宽度": "",
                    "高度": "",
                    "位置X": "",
                    "位置Y": "",
                    "位置Z": "",
                    "备注": "",
                },
            ]).to_csv(csv_dir / "3.1目标物理结构数据.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame([
                {"目标ID": "T001", "部件ID": "BJ0002", "三维模型数据文件": "old.stl", "长度": "", "宽度": "", "高度": "", "备注": ""}
            ]).to_csv(csv_dir / "3.2目标三维模型数据.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame([
                {"目标ID": "T001", "功能ID": "GN0001", "功能名称": "侦察"}
            ]).to_csv(csv_dir / "4.1目标功能结构数据.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame([
                {"目标ID": "T001", "功能ID": "GN0001", "部件ID": "BJ0002"}
            ]).to_csv(csv_dir / "4.3目标功能与部件映射数据.csv", index=False, encoding="utf-8-sig")

            execution_results = [
                SkillExecutionResult(
                    success=True,
                    output_files=[str(existing_stl)],
                    target_part="BJ0002",
                    op="translate",
                    message="translate success",
                    metadata={
                        "affected_parts": [
                            {"part_id": "BJ0002", "temp_output_path": str(existing_stl), "role": "primary"}
                        ]
                    },
                ),
                SkillExecutionResult(
                    success=True,
                    output_files=[str(added_stl)],
                    target_part="BJ0003",
                    op="add",
                    message="add success",
                    metadata={
                        "attach_to": "BJ0001",
                        "asset_request_used": {"content": "顶部新增防护笼", "category": "roof"},
                    },
                ),
                SkillExecutionResult(
                    success=False,
                    output_files=[],
                    target_part="BJ0001",
                    op="delete",
                    message="delete failed",
                ),
            ]

            result = export_source_table_syncs(
                csv_dir=csv_dir,
                output_dir=output_dir,
                execution_results=execution_results,
            )

            self.assertEqual(set(k for k in result.paths if k != "report"), {"2.1", "3.1", "3.2", "4.1", "4.3"})
            physical_out = pd.read_csv(result.paths["3.1"], encoding="utf-8-sig")
            model_out = pd.read_csv(result.paths["3.2"], encoding="utf-8-sig")

            existing_row = physical_out[physical_out["部件ID"] == "BJ0002"].iloc[0]
            self.assertEqual(existing_row["长度"], 10.0)
            self.assertEqual(existing_row["宽度"], 20.0)
            self.assertIn("STL同步:translate", existing_row["备注"])

            self.assertFalse((physical_out["部件ID"] == "BJ0001").any() and "delete failed" in str(physical_out.loc[0, "备注"]))

            added_row = physical_out[physical_out["部件ID"] == "BJ0003"].iloc[0]
            self.assertEqual(added_row["父部件ID"], "BJ0001")
            self.assertEqual(added_row["父部件名称"], "车身")
            self.assertEqual(added_row["长度"], 5.0)
            self.assertEqual(added_row["宽度"], 6.0)

            model_existing = model_out[model_out["部件ID"] == "BJ0002"].iloc[0]
            self.assertEqual(model_existing["三维模型数据文件"], "BJ0002.stl")
            model_added = model_out[model_out["部件ID"] == "BJ0003"].iloc[0]
            self.assertEqual(model_added["三维模型数据文件"], "BJ0003.stl")
            self.assertTrue(Path(result.paths["report"]).exists())


if __name__ == "__main__":
    unittest.main()
