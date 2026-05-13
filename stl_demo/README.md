# STL 文本驱动部件变更 Demo

这是一个围绕「**情报文本驱动 3D 部件变更**」的最小可运行闭环项目，核心流程为：

**情报文本 + 部件约束 + STL 网格 → LLM 结构化意图 → 规则校验 → 几何技能执行 → 修复与合理性检查 → 报告导出**

---

## 1. 项目分析（架构与流程）

### 1.1 工作流（LangGraph）
项目在 `app/graph/workflow.py` 中定义了固定流水线：

1. `load_inputs`：先调用 `scripts/build_part_constraints_v3.py` 生成约束，再读取约束与 STL 文件清单  
2. `generate_intelligence`：读取输入文本（无文本则自动 mock）  
3. `build_part_summary`：将约束数据整理为 LLM 可消费摘要  
4. `generate_change_intent`：调用 LLM 输出结构化变更意图  
5. `validate_change_intent`：对每条变更做参数与约束校验  
6. `prepare_stl_bundle`：将原始 STL 复制到输出目录作为工作集  
7. `apply_skills`：按操作类型调用 skill 执行实际变更  
8. `export_report`：导出 JSON + Markdown 报告

### 1.2 核心能力
- 支持操作：`translate` / `rotate` / `stretch` / `scale(delta_mm)` / `delete` / `add`  
- `add` 支持外部素材拉取 + 本地拟合（fit）  
- 每次几何修改后可执行网格修复与合理性检查  
- 校验失败的变更不会中断整体流程，而是记录 warning

### 1.3 LLM 模式
- `LLM_MODE=openai`：默认模式，走 OpenAI-compatible 接口  
- `LLM_MODE=mock`：离线模式，基于关键词生成可运行的模拟意图

> 注意：当前代码默认 `LLM_MODE` 为 `openai`，如离线演示请显式设置为 `mock`。

---

## 2. 目录结构

```text
stl_demo/
  app/
    graph/        # LangGraph 编排
    llm/          # Mock / OpenAI-compatible LLM 客户端
    services/     # 意图生成、校验、报告、网格修复、合理性检查等
    skills/       # 几何技能分发与具体操作
    config.py     # 环境配置
    models.py     # Pydantic 数据模型
  data/
    metadata/     # 约束与示例元数据
    stl_parts/    # 输入 STL
    intelligence/ # 输入情报文本
  output/         # 运行产物
  main.py
  requirements.txt
  README.md
```

---

## 3. 安装与运行

```bash
cd stl_demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py

# 可选：先检查本机 Python 版本、依赖包和关键项目导入是否满足
python ../scripts/check_environment.py
```

---

## 4. 配置说明（环境变量）

### 4.1 输入/输出路径
- `STL_PARTS_DIR`：输入 STL 目录（默认 `data/stl_parts`）
- `STL_TEXT_PATH`：情报文本路径（默认 `data/intelligence/input.txt`）
- `STL_PART_CONSTRAINTS_PATH`：部件约束文件（默认 `data/metadata/part_constraints.json`）
- `STL_OUTPUT_DIR`：输出根目录（默认 `output`）
- `output/tmp_stl/`：运行期 STL 临时工作区；最终快照仍只写入 `output/final_stl/`

### 4.1.1 约束构建脚本参数
- `PART_CONSTRAINTS_BUILDER_SCRIPT`：约束构建脚本路径（默认 `../scripts/build_part_constraints_v3.py`）
- `PART_CONSTRAINTS_CSV_DIR`：脚本输入 CSV 目录
- `PART_CONSTRAINTS_STL_ROOT`：脚本输入 STL 根目录
- `PART_CONSTRAINTS_OUT_DIR`：脚本输出目录（会产出 `part_constraints.json`）
- `PART_CONSTRAINTS_ENRICHED_EXCEL_DIR`：约束构建脚本额外导出的源表 Excel 副本目录（默认 `PART_CONSTRAINTS_OUT_DIR/enriched_excels`），只会回写/新增选定的 STL 几何字段。

### 4.2 LLM 相关
- `LLM_MODE=mock|openai`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `LLM_MODEL_NAME`

### 4.3 外部素材接口（add 场景）
- `ASSET_API_BASE_URL`
- `ASSET_API_REQUEST_TIMEOUT_SEC`
- `ASSET_TASK_POLL_INTERVAL_SEC`
- `ASSET_TASK_POLL_TIMEOUT_SEC`
- `ASSET_API_TOPK`（add/top_cover 执行时会请求 top5 候选素材并逐个拟合评分）
- `ASSET_AUTO_APPROVE`
- `ASSET_AUTO_ACCEPT_PROMPT`
- `ASSET_AUTO_ACCEPT_GENERATION`
- `ASSET_FORCE_GENERATE_DEFAULT`

### 4.4 add 姿态视觉评分（可选）
- `ADD_VISION_POSE_SELECTION_ENABLED=true|false`：是否在 add/top_cover fit 后渲染多组姿态候选并调用视觉模型评分，默认关闭。
- `ADD_VISION_POSE_MODEL_NAME`：视觉评分模型名，默认复用 `LLM_MODEL_NAME`。
- `ADD_VISION_POSE_IMAGE_SIZE`：候选渲染图片尺寸，默认 `768`。
- `ADD_VISION_POSE_MAX_CANDIDATES`：最多生成的姿态候选数量，默认 `12`，add/top_cover 流程会保证每个候选素材至少生成 12 个姿态候选。
- `ADD_VISION_POSE_RENDER_DIR`：候选图片输出目录，默认 `output/reports/pose_candidates`。

---

## 5. 输出产物

运行后将在 `output/` 下生成：

- `final_stl/`：最终 STL 快照集合（不再存放 `__tmp__*.stl` 临时文件）
- `tmp_stl/`：几何技能生成的临时 STL 工作文件，`prepare_stl_bundle` 每次运行会清空
- `reports/change_intent.json`：LLM 生成意图
- `reports/validated_changes.json`：校验结果
- `reports/execution_results.json`：执行结果
- `reports/mesh_repair_report.json`：网格修复记录
- `reports/reasonableness_report.json`：合理性检查记录
- `reports/demo_report.md`：汇总报告
- `data/metadata/enriched_excels/*_with_inference.xlsx`（或 `PART_CONSTRAINTS_ENRICHED_EXCEL_DIR` 指定目录）：约束构建阶段加载源表的 Excel 副本，仅回写/新增选定的 STL 几何字段，用于补全缺失/推测的几何信息。
- `logs/stl_demo.log`：运行日志

---

## 6. Requirements（运行要求）

### 6.1 Python 版本
- 建议：**Python 3.10+**

### 6.2 Python 依赖（`requirements.txt`）
- `langgraph>=0.2.50`
- `pydantic>=2.7.0`
- `trimesh>=4.4.0`
- `numpy>=1.26.0`
- `openai>=1.45.0`
- `Pillow>=10.0.0`
- `pyrender>=0.1.45`
- `pandas>=2.0.0`
- `requests>=2.31.0`
- `openpyxl>=3.1.0`

### 6.3 可选外部依赖
- 若使用 `LLM_MODE=openai`，需可访问兼容 OpenAI 的模型服务并配置 API Key。
- 若大量使用 `add`（外部素材生成/拉取），需可访问 `ASSET_API_BASE_URL` 指向的服务。
- 若启用 `ADD_VISION_POSE_SELECTION_ENABLED`，需确保 `OPENAI_BASE_URL` / `OPENAI_API_KEY` 指向支持图片输入的 OpenAI-compatible 接口，并且运行环境支持 `pyrender` 离屏渲染。

---

## 7. 推荐扩展方向

- 将情报输入从单文件扩展到 API/消息队列
- 增强 prompt 与 schema 约束，提高意图可控性
- 引入装配关系/碰撞检测
- 增加回滚机制与变更可视化对比（before/after）
