"""Pillar 4: Capability Discovery ("Have we solved this before? Do we have a tool? What patterns relate?")."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from . import FACTORY_ROOT
from .fabric import FabricIndex


def _extract_python_module_capabilities(factory_root: Path = FACTORY_ROOT) -> list[dict[str, Any]]:
    """Scan Python modules across runbooks, skills, and projects for reusable code building blocks."""
    capabilities: list[dict[str, Any]] = []
    scan_roots = [
        ("Factory Runbooks", factory_root / "runbooks" / "scripts"),
        ("Factory Skills", factory_root / ".github" / "skills"),
        ("PRJ-0001 Asset Catalog", factory_root / "projects" / "asset-catalog"),
        ("PRJ-0004 Personal Tracker", factory_root / "projects" / "personal-tracker"),
        ("PRJ-0005 Control Plane & ALM", factory_root / "projects" / "agent-lifecycle-management" / "control_plane"),
        ("WS-01 Knowledge Spikes", factory_root / "knowledge" / "sources"),
    ]
    for owner_label, root_dir in scan_roots:
        if not root_dir.is_dir():
            continue
        for py_path in sorted(root_dir.rglob("*.py")):
            if "__pycache__" in py_path.parts or py_path.name.startswith("test_"):
                continue
            rel = py_path.relative_to(factory_root).as_posix()
            try:
                source = py_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                module_doc = (ast.get_docstring(tree) or "").strip().splitlines()[0] if ast.get_docstring(tree) else ""
                classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_")]
                funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
            except Exception:
                module_doc = ""
                classes = []
                funcs = []
            if not module_doc and not classes and not funcs:
                continue
            symbols = classes + funcs[:8]
            capabilities.append(
                {
                    "id": f"MOD:{py_path.stem}",
                    "title": f"{py_path.name} ({owner_label})",
                    "category": "code_module",
                    "owner": owner_label,
                    "path": rel,
                    "summary": module_doc or f"Reusable Python module in {rel}",
                    "symbols": symbols,
                    "search_blob": f"{py_path.stem} {owner_label} {module_doc} {' '.join(symbols)} {rel}".lower(),
                }
            )
    return capabilities


def _load_registered_tools_and_patterns(factory_root: Path = FACTORY_ROOT) -> list[dict[str, Any]]:
    """Load Skills (SKL), Runbooks (RUN), and Patterns (PAT) as first-class capabilities."""
    items: list[dict[str, Any]] = []
    for reg_name, cat_label in [("skill-registry.json", "skill"), ("runbook-registry.json", "runbook")]:
        reg_path = factory_root / "cockpit" / reg_name
        if not reg_path.is_file():
            continue
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            for e in data.get("entries", []):
                summary = f"In: {e.get('input_schema', '—')} | Out: {e.get('output_schema', '—')}"
                items.append(
                    {
                        "id": e["id"],
                        "title": e["title"],
                        "category": cat_label,
                        "owner": e.get("skill_name") or e["id"],
                        "path": e.get("path", ""),
                        "summary": summary,
                        "symbols": e.get("upstream_refs", []) + e.get("downstream_refs", []),
                        "search_blob": f"{e['id']} {e['title']} {e.get('skill_name', '')} {summary}".lower(),
                    }
                )
        except Exception:
            continue

    pat_dir = factory_root / "knowledge" / "patterns"
    if pat_dir.is_dir():
        for pat_path in sorted(pat_dir.glob("PAT-*.md")):
            text = pat_path.read_text(encoding="utf-8", errors="replace")
            title_m = re.search(r'^title:\s*"([^"]+)"', text, re.M)
            id_m = re.search(r'^id:\s*"([^"]+)"', text, re.M)
            pid = id_m.group(1) if id_m else pat_path.stem[:8]
            ptitle = title_m.group(1) if title_m else pat_path.stem
            rel = pat_path.relative_to(factory_root).as_posix()
            items.append(
                {
                    "id": pid,
                    "title": ptitle,
                    "category": "pattern",
                    "owner": "Factory Pattern",
                    "path": rel,
                    "summary": " ".join(
                        line.strip()
                        for line in text.splitlines()
                        if line.strip() and not line.startswith(("---", "#", "id:", "title:", "type:", "created_date:", "status:", "upstream_refs:", "downstream_refs:", "tags:"))
                    )[:260],
                    "symbols": [],
                    "search_blob": text.lower(),
                }
            )
    return items


def discover_capabilities(
    problem_query: str = "",
    factory_root: Path = FACTORY_ROOT,
    fabric: FabricIndex | None = None,
) -> dict[str, Any]:
    """Answer:
    1) Have we solved this before? (Findings, Sources, Decisions, Conversations)
    2) Do we already have a tool or module for this? (Skills, Runbooks, Code Modules)
    3) What patterns are related? (PAT-#### records)
    """
    modules = _extract_python_module_capabilities(factory_root)
    registered = _load_registered_tools_and_patterns(factory_root)
    all_caps = registered + modules

    q = problem_query.strip().lower()
    tokens = [t for t in re.findall(r"[a-z0-9_]+", q) if len(t) >= 2]

    def score_item(item: dict[str, Any]) -> int:
        if not tokens:
            return 1
        blob = item["search_blob"]
        score = 0
        for t in tokens:
            if t in item["title"].lower():
                score += 5
            elif t in blob:
                score += 2
        return score

    if tokens:
        matched_caps = [c for c in all_caps if score_item(c) > 0]
        matched_caps.sort(key=score_item, reverse=True)
    else:
        matched_caps = all_caps

    tools_and_modules = [c for c in matched_caps if c["category"] in ("skill", "runbook", "code_module")]
    related_patterns = [c for c in matched_caps if c["category"] == "pattern"]

    # Also query the Fabric index for prior solved findings, decisions, sources, and chats
    solved_before: list[dict[str, Any]] = []
    if fabric is not None and q:
        fab_res = fabric.search(query=problem_query, limit=12)
        solved_before = [
            r
            for r in fab_res.get("results", [])
            if r["kind"] in ("finding", "decision", "source", "artifact", "conversation")
        ]
    elif fabric is not None:
        fab_res = fabric.search(query="", kind_filter="finding", limit=8)
        solved_before = fab_res.get("results", [])

    return {
        "query": problem_query,
        "summary": {
            "total_cataloged_capabilities": len(all_caps),
            "matching_tools_and_modules": len(tools_and_modules),
            "matching_patterns": len(related_patterns),
            "prior_solutions_and_findings": len(solved_before),
        },
        "have_we_solved_this_before": solved_before,
        "existing_tools_and_modules": tools_and_modules[:20],
        "related_patterns": related_patterns,
    }
