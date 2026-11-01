"""Read-only, provenance-backed decision guidance from canonical incubator records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .fabric import collect_knowledge_entities


DECISION_TOPICS = {
    "infrastructure-decision": {
        "title": "Infrastructure & hosting",
        "questions": [
            "What must remain available when the local machine is offline?",
            "What are the workload duration, data lifecycle, latency and compliance constraints?",
            "What operating burden and budget can the operator actually support?",
        ],
        "alternatives": [
            "Keep local execution where persistence and sharing are not required.",
            "Evaluate managed application/data services for reduced operational burden.",
            "Evaluate containers and workers for long-running or stateful workloads.",
        ],
    },
    "coordination-recoverability": {
        "title": "Coordination & recoverability",
        "questions": [
            "Which handoffs create value, and which merely compensate for missing context?",
            "Can each component consume/produce work and expose/receive observable state?",
            "What evidence, alternatives and recovery path would remain after a proposed action?",
        ],
        "alternatives": [
            "Reuse existing records and reduce duplicate outputs before adding a new component.",
            "Propose a reversible workflow with explicit human review.",
            "Retain specialist coordination where its benefit outweighs its attention cost.",
        ],
    },
    "capability-routing": {
        "title": "Capability & context routing",
        "questions": [
            "What affordance does this task require, independent of provider?",
            "Which candidate has verified access and relevant context for this specific task?",
            "What scarce capability would an assignment consume, and what work would it displace?",
        ],
        "alternatives": [
            "Reuse an existing skill/runbook or context-bearing component.",
            "Reserve a specialist for tasks that require its unique affordance.",
            "Defer allocation until missing access, state or outcome evidence is verified.",
        ],
    },
}


def build_decision_aid(
    factory_root: Path,
    topic: str = "infrastructure-decision",
    operator_context: str = "",
) -> dict[str, Any]:
    """Select by an explicit topic tag, never infer approval, access or readiness."""
    if topic not in DECISION_TOPICS:
        raise ValueError(f"Unknown decision topic: {topic}")
    root = factory_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError("The configured incubator directory does not exist.")
    entities = collect_knowledge_entities(root)
    records = []
    for entity in sorted(entities.values(), key=lambda item: item["id"]):
        tags = entity.get("tags", [])
        if not isinstance(tags, list) or topic not in tags:
            continue
        path = Path(entity["abs_path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Decision record {entity['id']} is outside the configured incubator.")
        references = []
        for ref_id in entity["upstream_refs"]:
            reference = entities.get(ref_id)
            references.append({
                "id": ref_id,
                "title": reference["title"] if reference else "Unresolved canonical reference",
                "status": reference["status"] if reference else "unknown",
                "path": reference["path"] if reference else "",
                "resolved": reference is not None,
            })
        records.append({
            "id": entity["id"],
            "title": entity["title"],
            "kind": entity["kind"],
            "status": entity["status"],
            "created_date": entity["created_date"],
            "path": entity["path"],
            "body": entity["body"],
            "upstream_refs": references,
        })
    return {
        "topic": topic,
        **DECISION_TOPICS[topic],
        "operator_context": operator_context.strip(),
        "records": records,
        "mode": "read-only-advisory",
        "uncertainty": (
            "Record statuses are canonical labels, not verified approval or operational readiness. "
            "Operator context is unverified input, not measured cost, access or capacity. "
            "No provider is selected and no work is dispatched."
        ),
    }
