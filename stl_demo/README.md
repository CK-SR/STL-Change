# STL 文本驱动部件变更 Demo

最小可运行闭环：**元数据 + STL + 情报文本 -> LLM 变更意图 -> 规则校验 -> Skill 几何修改 -> 报告输出**。

## 功能说明
- 加载 metadata JSON 并扫描 STL 目录
- 生成 5~10 条 mock 情报文本
- 支持统一 LLM 接口（Mock / OpenAI-compatible）
- 生成结构化 change intent（JSON）
- 执行最小规则校验（失败不中断）
- 执行 scale/translate/rotate/delete/add(copy) 技能
- 输出修改 STL、JSON 报告和 Markdown 报告

## 目录结构
```text
stl_demo/
  app/
    config.py
    models.py
    state.py
    llm/
    services/
    skills/
    graph/
    utils/
  data/
    metadata/
    stl_parts/
  output/
  main.py
  requirements.txt
  README.md
```

## 安装
```bash
cd stl_demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行
```bash
python main.py
```

可选环境变量：
- `STL_METADATA_PATH`：metadata JSON 路径
- `STL_PARTS_DIR`：STL 目录
- `LLM_MODE=mock|openai`
- `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL_NAME`

## 输入数据说明
- 默认 metadata: `data/metadata/metadata.json`
- 默认 STL 目录: `data/stl_parts/`
- metadata 使用现有中文字段，代码通过 Pydantic alias 兼容

## 输出结果
在 `output/` 下生成：
- `modified_stl/`：修改后的 STL
- `reports/change_intent.json`
- `reports/validated_changes.json`
- `reports/execution_results.json`
- `reports/demo_report.md`
- `logs/stl_demo.log`

## 切换 LLM 客户端
- 默认 `LLM_MODE=mock`（离线可跑）
- 设置 `LLM_MODE=openai` 并提供 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 即可走兼容 API（可配置 `LLM_MODEL_NAME=Qwen3-Next-80B`）

## 可扩展方向
- 真实情报输入接入（文件/API）
- 更强 intent 约束与 schema 输出
- 装配关系和几何冲突校验
- 更细粒度局部网格编辑
- 增加回滚、审计与可视化 diff
