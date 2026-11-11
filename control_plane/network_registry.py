"""Read-only view of the network registry: what the network has started and where it lives.

The registry is a directory of one JSON file per entry, kept in its own repository so it
belongs to the network and not to any single node. This module only reads it. Entries are
written by the node that initializes something; nothing here creates, edits or trusts them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MAX_ENTRY_BYTES = 64 * 1024
MAX_ENTRIES = 5000
REQUIRED = ("id", "kind", "title", "status", "home", "initialized_by", "initialized_on", "origin")


class NetworkRegistryError(ValueError):
    pass


def find_registry_root(network_root: Path, explicit: Path | None = None) -> Path:
    """Resolve the registry checkout: explicit path, then DEVNET_REGISTRY_ROOT, then the default layout."""
    if explicit is not None:
        return Path(explicit).resolve()
    if "DEVNET_REGISTRY_ROOT" in os.environ:
        return Path(os.environ["DEVNET_REGISTRY_ROOT"]).resolve()
    for candidate in (
        network_root / "devnet" / "network-registry" / "main",
        network_root / "network-registry",
    ):
        if (candidate / "entries").is_dir():
            return candidate
    return network_root / "devnet" / "network-registry" / "main"


def load_entries(registry_root: Path) -> dict[str, Any]:
    """Return valid entries plus a list of files that could not be used, never raising on one bad file."""
    entries_dir = Path(registry_root) / "entries"
    if not entries_dir.is_dir():
        raise NetworkRegistryError(f"no registry entries directory at {entries_dir}")
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(entries_dir.glob("*.json"))[:MAX_ENTRIES]:
        try:
            if path.stat().st_size > MAX_ENTRY_BYTES:
                raise ValueError("file too large")
            entry = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entry, dict):
                raise ValueError("not a JSON object")
            missing = [key for key in REQUIRED if key not in entry]
            if missing:
                raise ValueError("missing " + ", ".join(missing))
            if entry["id"] != path.stem:
                raise ValueError("id does not match filename")
        except (OSError, ValueError) as exc:
            skipped.append({"file": path.name, "reason": str(exc)})
            continue
        entries.append(entry)
    return {"registry_root": str(registry_root), "entries": entries, "skipped": skipped}


def list_entries(
    registry_root: Path, kind: str = "", status: str = "", initialized_by: str = "",
) -> dict[str, Any]:
    loaded = load_entries(registry_root)
    selected = [
        entry for entry in loaded["entries"]
        if (not kind or entry["kind"] == kind)
        and (not status or entry["status"] == status)
        and (not initialized_by or entry["initialized_by"] == initialized_by)
    ]
    return {
        "registry_root": loaded["registry_root"],
        "count": len(selected),
        "total": len(loaded["entries"]),
        "entries": selected,
        "skipped": loaded["skipped"],
    }


def get_entry(registry_root: Path, entry_id: str) -> dict[str, Any]:
    for entry in load_entries(registry_root)["entries"]:
        if entry["id"] == entry_id:
            return entry
    raise NetworkRegistryError(f"no registry entry with id {entry_id}")
