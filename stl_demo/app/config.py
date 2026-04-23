from pathlib import Path
import os


class Settings:
    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.project_root / "data"

        self.stl_dir = Path(os.getenv("STL_PARTS_DIR", str(self.data_dir / "stl_parts")))
        self.excel_path = Path(
            os.getenv(
                "STL_EXCEL_PATH",
                str(self.data_dir / "metadata" / "airbus-a320neo_original.xlsx"),
            )
        )
        self.text_path = Path(
            os.getenv("STL_TEXT_PATH", str(self.data_dir / "intelligence" / "input.txt"))
        )
        self.output_dir = Path(os.getenv("STL_OUTPUT_DIR", str(self.project_root / "output")))

        self.part_constraints_path = Path(
            os.getenv(
                "STL_PART_CONSTRAINTS_PATH",
                str(self.data_dir / "metadata" / "part_constraints.json"),
            )
        )
        self.part_constraints_builder_script = Path(
            os.getenv(
                "PART_CONSTRAINTS_BUILDER_SCRIPT",
                str(self.project_root.parent / "scripts" / "build_part_constraints_v3.py"),
            )
        )
        self.part_constraints_csv_dir = Path(
            os.getenv("PART_CONSTRAINTS_CSV_DIR", str(self.data_dir / "metadata" / "csv"))
        )
        self.part_constraints_stl_root = Path(
            os.getenv("PART_CONSTRAINTS_STL_ROOT", str(self.stl_dir))
        )
        self.part_constraints_out_dir = Path(
            os.getenv("PART_CONSTRAINTS_OUT_DIR", str(self.part_constraints_path.parent))
        )

        self.final_stl_dir = self.output_dir / "final_stl"
        self.logs_dir = self.output_dir / "logs"
        self.reports_dir = self.output_dir / "reports"
        self.excels_dir = self.output_dir / "excels"
        self.asset_download_dir = self.output_dir / "downloaded_assets"

        self.updated_excel_path = self.excels_dir / "updated_parts.xlsx"
        self.change_table_path = self.excels_dir / "change_table.xlsx"

        self.llm_mode = os.getenv("LLM_MODE", "openai")
        self.model_name = os.getenv("LLM_MODEL_NAME", "qwen3.5-122b-a10b")
        self.base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.api_key = os.getenv("OPENAI_API_KEY", "")

        # ===== 外部素材接口 =====
        self.asset_api_base_url = os.getenv("ASSET_API_BASE_URL", "http://192.168.130.111:7100")
        self.asset_api_request_timeout_sec = float(
            os.getenv("ASSET_API_REQUEST_TIMEOUT_SEC", "600")
        )
        self.asset_task_poll_interval_sec = float(
            os.getenv("ASSET_TASK_POLL_INTERVAL_SEC", "5")
        )
        self.asset_task_poll_timeout_sec = float(
            os.getenv("ASSET_TASK_POLL_TIMEOUT_SEC", "9000")
        )

        # add 默认走自动化闭环，避免当前 demo 卡在人审中间态
        self.asset_api_topk = int(os.getenv("ASSET_API_TOPK", "30"))
        self.asset_auto_approve = os.getenv("ASSET_AUTO_APPROVE", "true").lower() == "true"
        self.asset_auto_accept_prompt = (
            os.getenv("ASSET_AUTO_ACCEPT_PROMPT", "true").lower() == "true"
        )
        self.asset_auto_accept_generation = (
            os.getenv("ASSET_AUTO_ACCEPT_GENERATION", "true").lower() == "true"
        )
        self.asset_force_generate_default = (
            os.getenv("ASSET_FORCE_GENERATE_DEFAULT", "false").lower() == "false"
        )


settings = Settings()
