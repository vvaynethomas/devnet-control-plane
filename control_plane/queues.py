"""Pillar 2: Cross-network Queue Aggregation, Blocker & Acceptance Triage, and Next-Action Router."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import DEV_NETWORK_ROOT, FACTORY_ROOT

ID_PATTERN = re.compile(r"\b(SRC|FND|PAT|DEC|PRM|WF|RUN|SKL|PRJ|ART|BL|ALM|LP|CAT)-\d{3,4}\b")

# Data-driven Next-Action Router table (PAT-0001 / BL-0014)
NEXT_ACTION_ROUTES = [
    {
        "input_type": "Source document, paper, URL, or external spec",
        "entity_id": "SKL-0005",
        "procedure": "Librarian intake / reconcile-import -> produces SRC-#### and FND-####",
        "path": ".github/skills/reconcile-import/SKILL.md",
    },
    {
        "input_type": "Raw notes, chat transcript excerpt, or product idea",
        "entity_id": "SKL-0003",
        "procedure": "Planner agent via ingest-scrap -> prioritized tasks, findings, or ADR candidates",
        "path": ".github/skills/ingest-scrap/SKILL.md",
    },
    {
        "input_type": "Architectural boundary, storage, or lifecycle decision",
        "entity_id": "SKL-0001",
        "procedure": "Architect agent via adr-scaffold -> draft DEC-#### with 3+ options",
        "path": ".github/skills/adr-scaffold/SKILL.md",
    },
    {
        "input_type": "Backlog grooming or status/priority alignment",
        "entity_id": "SKL-0002",
        "procedure": "Planner agent via backlog-curator -> reconciled BACKLOG.md and ROADMAP.md",
        "path": ".github/skills/backlog-curator/SKILL.md",
    },
    {
        "input_type": "Product graduation readiness & standalone staging",
        "entity_id": "SKL-0009",
        "procedure": "Architect/Implementer via product-readiness (SKL-0009) & package-product (SKL-0010)",
        "path": ".github/skills/product-readiness/SKILL.md",
    },
    {
        "input_type": "Product incubation or maintenance lesson to return to lab",
        "entity_id": "RUN-0002",
        "procedure": "Librarian via RUN-0002 (Metabolize product learning workbench)",
        "path": "runbooks/RUN-0002-metabolize-product-learning.md",
    },
    {
        "input_type": "Prompt framing or agent behavioral comparison hypothesis",
        "entity_id": "ART-0007",
        "procedure": "Interaction Lab in Control Plane -> compose InteractionFrame & run side-by-side eval",
        "path": "projects/agent-lifecycle-management/artifacts/ART-0007-development-network-control-plane-and-interaction-lab.md",
    },
]


def _classify_status(raw_status: str, depends_on: str, scope_text: str) -> tuple[str, bool]:
    """Return normalized bucket ('awaiting_acceptance', 'blocked', 'open', 'done') and is_pointer flag."""
    s = raw_status.strip()
    s_lower = s.lower()
    is_pointer = (
        "origin snapshot" in s_lower
        or "product delivery pointer" in scope_text.lower()
        or "this row is a pointer" in scope_text.lower()
    )
    if s_lower.startswith("done"):
        return "done", is_pointer
    if s_lower.startswith("awaiting acceptance"):
        return "awaiting_acceptance", is_pointer
    if (
        "blocked" in s_lower
        or "pending" in s_lower
        or ("approval" in depends_on.lower() and not s_lower.startswith("done"))
    ):
        return "blocked", is_pointer
    return "open", is_pointer


def _parse_backlog_markdown(
    md_path: Path,
    owner_id: str,
    owner_title: str,
    rel_source_path: str,
) -> list[dict[str, Any]]:
    if not md_path.is_file():
        return []
    items: list[dict[str, Any]] = []
    current_heading = "General"
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("## "):
            current_heading = stripped.lstrip("#").strip()
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        first = cells[0]
        if first in ("ID", "Origin ID", "Task", ":---", "---") or set(first) <= {":", "-"}:
            continue
        if not re.match(r"^[A-Z]{2,4}-\d{3,4}$", first):
            continue

        # Factory & PRJ-0004 format: | ID | Task | Acceptance criteria | Depends on | Status |
        # PRJ-0005 & PRJ-0002 format: | Task | Scope and acceptance evidence | Depends on | Priority | Status |
        if len(cells) >= 5 and re.match(r"^(P[012]|Unassigned|Not separately assigned)", cells[3]):
            task_id = cells[0]
            title_and_scope = cells[1]
            dot_idx = title_and_scope.find(". ")
            if dot_idx != -1 and dot_idx < 120:
                title = title_and_scope[:dot_idx].strip()
                criteria = title_and_scope[dot_idx + 2 :].strip()
            else:
                title = title_and_scope[:100]
                criteria = title_and_scope
            depends_on = cells[2]
            priority = cells[3]
            status_raw = cells[4]
        else:
            task_id = cells[0]
            title = cells[1]
            criteria = cells[2]
            depends_on = cells[3]
            priority = (
                "P0"
                if "P0" in current_heading
                else "P1"
                if "P1" in current_heading
                else "P2"
                if "P2" in current_heading
                else "Unassigned"
            )
            status_raw = cells[4]

        bucket, is_pointer = _classify_status(status_raw, depends_on, f"{title} {criteria}")
        referenced_ids = sorted(set(m.group(0) for m in ID_PATTERN.finditer(f"{criteria} {depends_on} {status_raw}")))
        items.append(
            {
                "id": task_id,
                "owner_id": owner_id,
                "owner_title": owner_title,
                "section": current_heading,
                "priority": priority,
                "title": title,
                "criteria": criteria,
                "depends_on": depends_on,
                "status_raw": status_raw,
                "bucket": bucket,
                "is_pointer": is_pointer,
                "source_path": rel_source_path,
                "abs_path": str(md_path.resolve()),
                "line": line_no,
                "referenced_ids": referenced_ids,
            }
        )
    return items


def aggregate_queues(
    factory_root: Path = FACTORY_ROOT,
    network_root: Path = DEV_NETWORK_ROOT,
) -> dict[str, Any]:
    """Aggregate backlog queues across the Factory, incubated projects, and sibling product repos."""
    all_items: list[dict[str, Any]] = []

    # 1. Root Factory BACKLOG.md
    root_backlog = factory_root / "BACKLOG.md"
    all_items.extend(
        _parse_backlog_markdown(root_backlog, "FACTORY", "Lab Factory (Root Queue)", "BACKLOG.md")
    )

    # 2. Incubated project queues
    project_queues = [
        ("PRJ-0002", "Learning & Knowledge Platform", "projects/learning-platform/BACKLOG.md"),
        ("PRJ-0004", "Personal Tracker", "projects/personal-tracker/BACKLOG.md"),
        ("PRJ-0005", "Agent Lifecycle Management", "projects/agent-lifecycle-management/BACKLOG.md"),
    ]
    for prj_id, prj_title, rel_path in project_queues:
        q_path = factory_root / rel_path
        if q_path.is_file():
            all_items.extend(_parse_backlog_markdown(q_path, prj_id, prj_title, rel_path))

    # 3. External graduated / sibling repository queues (if present)
    for ext_slug, ext_id, ext_title in [
        ("digital-asset-catalog", "PRJ-0001-EXT", "Digital Asset Catalog (Standalone Repo)"),
    ]:
        ext_backlog = network_root / ext_slug / "BACKLOG.md"
        if ext_backlog.is_file():
            all_items.extend(
                _parse_backlog_markdown(
                    ext_backlog,
                    ext_id,
                    ext_title,
                    f"../{ext_slug}/BACKLOG.md",
                )
            )

    # Filter out historical origin pointers when computing active counts
    active_items = [item for item in all_items if not item["is_pointer"]]

    awaiting_acceptance = [i for i in active_items if i["bucket"] == "awaiting_acceptance"]
    blocked_items = [i for i in active_items if i["bucket"] == "blocked"]
    open_items = [i for i in active_items if i["bucket"] == "open"]
    done_items = [i for i in active_items if i["bucket"] == "done"]

    # Build prioritized Next Actions list:
    # 1) Awaiting human acceptance (highest leverage for the human operator to unblock downstream work)
    # 2) Ready P1 Open items
    # 3) Blocked items needing an operator ADR decision
    next_actions: list[dict[str, Any]] = []
    for item in awaiting_acceptance[:6]:
        next_actions.append(
            {
                "kind": "Human Acceptance Gate",
                "badge": "awaiting-acceptance",
                "id": item["id"],
                "owner": item["owner_id"],
                "title": item["title"],
                "reason": item["status_raw"],
                "source_path": item["source_path"],
                "line": item["line"],
            }
        )
    for item in open_items:
        if item["priority"].startswith("P1") or item["owner_id"] == "PRJ-0005":
            next_actions.append(
                {
                    "kind": "Ready Work Slice",
                    "badge": "open",
                    "id": item["id"],
                    "owner": item["owner_id"],
                    "title": item["title"],
                    "reason": f"Priority: {item['priority']} · Depends on: {item['depends_on']}",
                    "source_path": item["source_path"],
                    "line": item["line"],
                }
            )
            if len(next_actions) >= 12:
                break

    return {
        "summary": {
            "total_rows": len(all_items),
            "active_non_pointer_rows": len(active_items),
            "awaiting_acceptance": len(awaiting_acceptance),
            "blocked": len(blocked_items),
            "open": len(open_items),
            "done": len(done_items),
        },
        "next_actions": next_actions,
        "router_routes": NEXT_ACTION_ROUTES,
        "awaiting_acceptance": awaiting_acceptance,
        "blocked": blocked_items,
        "open": open_items,
        "done": done_items,
        "all_items": all_items,
    }


def match_router_route(input_description: str) -> dict[str, Any]:
    """Match an operator input type description to a registered procedure (PAT-0001)."""
    q = input_description.strip().lower()
    if not q:
        return {"matched": False, "route": None, "all_routes": NEXT_ACTION_ROUTES}
    keyword_map = [
        (["paper", "pdf", "source", "import", "zip", "seed", "archive"], NEXT_ACTION_ROUTES[0]),
        (["note", "scrap", "idea", "chat", "transcript"], NEXT_ACTION_ROUTES[1]),
        (["adr", "decision", "architecture", "boundary"], NEXT_ACTION_ROUTES[2]),
        (["backlog", "groom", "priority", "roadmap", "queue"], NEXT_ACTION_ROUTES[3]),
        (["graduate", "handover", "package", "standalone", "readiness"], NEXT_ACTION_ROUTES[4]),
        (["lesson", "metabolize", "learning", "incident"], NEXT_ACTION_ROUTES[5]),
        (["frame", "affect", "cute", "caveman", "eval", "interaction"], NEXT_ACTION_ROUTES[6]),
    ]
    for keywords, route in keyword_map:
        if any(k in q for k in keywords):
            return {"matched": True, "route": route, "all_routes": NEXT_ACTION_ROUTES}
    return {
        "matched": False,
        "message": f"Unknown input type '{input_description}'. Select a canonical route below or register a new PRM/SKL if repeated >= 3 times.",
        "route": None,
        "all_routes": NEXT_ACTION_ROUTES,
    }
