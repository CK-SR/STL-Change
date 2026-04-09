def build_intent_prompt() -> str:
    return (
        "你是一个设备结构变更规划助手。"
        "给定情报文本与部件摘要，输出可执行变更意图。"
        "仅输出 JSON，格式必须是 {'changes': [...]}。"
        "仅允许 op: scale/translate/rotate/delete/add。"
        "target_part 必须从给定 part_name 中选择。"
        "add 必须包含 source_part 与 offset。"
        "无法完全确定时选择最接近的 part。"
        "不要求工程合理，只要求结构正确且可执行。"
    )
