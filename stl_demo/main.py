from __future__ import annotations

import logging

from app.config import settings
from app.graph.workflow import build_workflow
from app.models import DemoState
from app.utils.file_utils import ensure_dirs
from app.utils.logger import setup_logging


def main() -> None:
    ensure_dirs(
        settings.output_dir,
        settings.final_stl_dir,
        settings.logs_dir,
        settings.reports_dir,
        settings.excels_dir,
    )
    setup_logging(settings.logs_dir / "stl_demo.log")
    logger = logging.getLogger("main")

    app = build_workflow()
    final_state = DemoState.model_validate(app.invoke(DemoState()))

    logger.info("Workflow finished.")
    logger.info("Report paths: %s", final_state.report_paths)


if __name__ == "__main__":
    main()