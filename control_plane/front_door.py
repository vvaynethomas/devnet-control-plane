"""What an agent in any repository needs to find the network: principles, playbooks, lessons.

Everything here reads from where it already lives. Principles are the registry's
PRINCIPLES.md; playbooks are SKILL.md files in the registry, the incubator and the harvest
playbooks repository; lessons belong to the Epistemic Service and are asked for through its own
command line. Nothing is copied into the control plane.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import network_registry

MAX_PLAYBOOK_BYTES = 64 * 1024


def playbook_sources(registry_root: Path, factory_root: Path, network_root: Path) -> list[tuple[str, Path]]:
    return [("network-registry", Path(registry_root) / "playbooks"),
            ("product-incubator", Path(factory_root) / ".github" / "skills"),
            ("harvest-playbooks", Path(network_root) / "shared" / "harvest-playbooks" / "main" / "playbooks")]


def _front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    fields: dict[str, str] = {}
    for line in (match.group(1).splitlines() if match else []):
        key, _, value = line.partition(":")
        if key.strip() in ("name", "description"):
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def list_playbooks(registry_root: Path, factory_root: Path, network_root: Path, query: str = "") -> dict[str, Any]:
    found, missing = [], []
    for owner, folder in playbook_sources(registry_root, factory_root, network_root):
        if not folder.is_dir():
            missing.append(f"{owner}: {folder}")
            continue
        for path in sorted(folder.glob("*/SKILL.md")):
            try:
                fields = _front_matter(path.read_text(encoding="utf-8", errors="replace")[:MAX_PLAYBOOK_BYTES])
            except OSError:
                continue
            found.append({"name": fields.get("name") or path.parent.name, "owner": owner,
                          "description": fields.get("description", ""), "path": str(path)})
    if query.strip():
        stop_words = {"a", "an", "and", "are", "can", "do", "for", "how", "i", "in", "is", "it", "of", "the", "to", "what"}
        terms = set(re.findall(r"\w+", query.casefold())) - stop_words
        ranked = []
        for item in found:
            name = set(re.findall(r"\w+", item["name"].casefold()))
            description = set(re.findall(r"\w+", item["description"].casefold()))
            score = len(terms & name) * 3 + len(terms & description)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: -pair[0])
        found = [item for _, item in ranked]
    return {"count": len(found), "playbooks": found, "sources_missing": missing,
            "note": "A playbook is a procedure, read from its owner's repository. Read it in full before following it."}


def get_playbook(name: str, registry_root: Path, factory_root: Path, network_root: Path) -> dict[str, Any]:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        raise ValueError("playbook names are lowercase words joined by hyphens")
    for item in list_playbooks(registry_root, factory_root, network_root)["playbooks"]:
        if item["name"] == name or Path(item["path"]).parent.name == name:
            path = Path(item["path"])
            if path.stat().st_size > MAX_PLAYBOOK_BYTES:
                raise ValueError("playbook is larger than 64 KiB")
            return {**item, "text": path.read_text(encoding="utf-8", errors="replace"),
                    "folder_files": sorted(p.name for p in path.parent.iterdir())}
    raise ValueError(f"no playbook named {name}")


def epistemic_root(network_root: Path) -> Path:
    return Path(os.environ.get("DEVNET_EPISTEMIC_ROOT") or Path(network_root) / "devnet" / "epistemic-service" / "main")


def ask_lessons(network_root: Path, task: str, repo: str = "", stage: str = "", limit: int = 7) -> dict[str, Any]:
    """Ask the Epistemic Service, which owns lessons and their evidence."""
    root = epistemic_root(network_root)
    if not (root / "epistemic" / "__main__.py").is_file():
        return {"unavailable": f"Epistemic Service not found at {root}; set DEVNET_EPISTEMIC_ROOT"}
    command = [sys.executable, "-m", "epistemic", "ask", str(task), "--repo", repo or "", "--limit", str(limit)]
    if stage:
        command += ["--stage", stage]
    # stdin must not be inherited: under the stdio MCP server it is the protocol pipe, and a child holding it hangs.
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=30, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        return {"unavailable": (done.stderr or done.stdout).strip()[:300]}
    return json.loads(done.stdout)


def get_brief(network_root: Path, brief_id: str) -> dict[str, Any]:
    """A stored decision brief, read from the Epistemic Service."""
    root = epistemic_root(network_root)
    if not (root / "epistemic" / "__main__.py").is_file():
        return {"unavailable": f"Epistemic Service not found at {root}"}
    done = subprocess.run([sys.executable, "-m", "epistemic", "brief", "get", str(brief_id)], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        return {"unavailable": (done.stderr or done.stdout).strip()[:300]}
    return json.loads(done.stdout)


def bootstrap(registry_root: Path, factory_root: Path, network_root: Path, data_dir: Path) -> dict[str, Any]:
    """Small on purpose: where things are and how to ask, not the things themselves."""
    principles_path = Path(registry_root) / "PRINCIPLES.md"
    try:
        principles = principles_path.read_text(encoding="utf-8")
        # Only the numbered principles: the file's preamble and its "how to reach" section repeat "how" below.
        start = principles.find("\n1. ")
        end = principles.find("\n## ", start + 1) if start >= 0 else -1
        if start >= 0:
            principles = principles[start + 1:end if end > 0 else None].strip() + f"\n(full text: {principles_path})"
        principles = principles[:4000]
    except OSError:
        principles = f"(no PRINCIPLES.md at {principles_path})"
    try:
        entries = network_registry.load_entries(registry_root)["entries"]
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    except (OSError, ValueError) as exc:
        counts = {"unavailable": str(exc)}  # type: ignore[dict-item]
    folder = Path(data_dir) / "commissions"
    open_commissions = []
    for path in sorted(folder.glob("COM-*.json")) if folder.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] not in ("done", "withdrawn"):
            open_commissions.append({"id": record["id"], "state": record["state"], "next": record["next"]})
    playbooks = list_playbooks(registry_root, factory_root, network_root)
    return {
        "network": "A set of repositories that share a registry, a front door (this control plane) and an "
                   "Epistemic Service. Each repository owns its own work; the network keeps track and helps.",
        "principles": principles,
        "how": {
            "ask for lessons": "lessons_ask(task, repo, stage) before building (stage before-building) and before saying "
                               "work is done (stage before-claiming-done).",
            "request new work": "Only when the owner asks for work: commission_check(title, need), then commission_open(...), "
                                "then triage and commission_recommend with sources. Do not start new products, tools or "
                                "services inside another repository.",
            "note something said in passing": "registry_note(id, text, by): recorded on the existing entry, no commission, "
                                              "nothing queued for the owner.",
            "bring the owner a decision": "Follow the research-brief playbook: research_start(question) on the epistemic "
                                          "server, collect dated primary sources, brief_submit. Then commission_recommend "
                                          "with its sources or brief id. Never ask the owner to choose between unsourced options.",
            "follow a procedure": "playbook_list(query) searches by task; playbook_get(name) returns the instructions.",
            "see what exists": "registry_list(kind, status) and registry_show(id); phone_home_check(query) for capabilities.",
            "report what you learned": "lessons_propose on the Epistemic Service, with evidence and stated uncertainty.",
            "from a shell": "devnet bootstrap | lessons ask | commission ... | playbook list|get | registry list|show",
        },
        "playbooks": [{"name": p["name"], "owner": p["owner"]} for p in playbooks["playbooks"]],
        "state": {"registry_by_status": counts, "open_commissions": open_commissions},
    }
