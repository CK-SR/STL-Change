from pathlib import Path
import os


class Settings:
    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.project_root / "data"
        # self.metadata_path = Path(
        #     os.getenv("STL_METADATA_PATH", str(self.data_dir / "metadata" / "semantic_labels.json"))
        # )
        self.stl_dir = Path(os.getenv("STL_PARTS_DIR", str(self.data_dir / "stl_parts")))
        self.excel_path = Path(os.getenv("STL_EXCEL_PATH", str(self.data_dir / "metadata" / "airbus-a320neo_original.xlsx")))
        self.text_path = Path(os.getenv("STL_TEXT_PATH", str(self.data_dir / "intelligence" / "input.txt")))

        self.output_dir = Path(os.getenv("STL_OUTPUT_DIR", str(self.project_root / "output")))

        self.final_stl_dir = self.output_dir / "final_stl"
        self.logs_dir = self.output_dir / "logs"
        self.reports_dir = self.output_dir / "reports"
        self.excels_dir = self.output_dir / "excels"
        self.updated_excel_path = self.excels_dir / "updated_parts.xlsx"
        self.change_table_path = self.excels_dir / "change_table.xlsx"

        self.llm_mode = os.getenv("LLM_MODE", "openai")
        self.model_name = os.getenv("LLM_MODEL_NAME", "qwen3-next-80b-a3b-instruct")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.api_key = os.getenv("OPENAI_API_KEY", "")


settings = Settings()
