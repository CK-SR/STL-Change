from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.models import DemoState
from app.graph.nodes import (
    apply_skills,
    build_part_summary_node,
    export_report,
    generate_change_intent_node,
    generate_intelligence,
    load_inputs,
    prepare_stl_bundle_node,
    validate_change_intent_node,
)


def build_workflow():
    graph = StateGraph(DemoState)

    graph.add_node("load_inputs", load_inputs)
    graph.add_node("generate_intelligence", generate_intelligence)
    graph.add_node("build_part_summary", build_part_summary_node)
    graph.add_node("generate_change_intent", generate_change_intent_node)
    graph.add_node("validate_change_intent", validate_change_intent_node)
    graph.add_node("prepare_stl_bundle", prepare_stl_bundle_node)
    graph.add_node("apply_skills", apply_skills)
    graph.add_node("export_report", export_report)

    graph.set_entry_point("load_inputs")

    graph.add_edge("load_inputs", "generate_intelligence")
    graph.add_edge("generate_intelligence", "build_part_summary")
    graph.add_edge("build_part_summary", "generate_change_intent")
    graph.add_edge("generate_change_intent", "validate_change_intent")
    graph.add_edge("validate_change_intent", "prepare_stl_bundle")
    graph.add_edge("prepare_stl_bundle", "apply_skills")
    graph.add_edge("apply_skills", "export_report")
    graph.add_edge("export_report", END)

    return graph.compile()