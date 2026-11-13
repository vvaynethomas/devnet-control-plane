"""Read-only inspection of an explicitly selected ALM lifecycle ledger (DNCP-012).

Validation is done by the pinned, provenance-checked `alm-lifecycle-core`; DNCP adds no
second validator. Nothing is imported into DNCP, copied, installed, promoted or executed,
and a valid ledger is never reported as trusted: its evaluations and approvals are
recorded assertions.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

from .material_capability import _prepare_owned
from .material_pins import ALM_COMMIT, ALM_URL, ALM_VERSION, ALM_WHEEL_SHA256
from .verified_package import SNAPSHOT_LOAD_LOCK, load_package_from_snapshot, unload_package_snapshot

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_LEDGERS = 20
MAX_COMPARED_FILE_BYTES = 8 * 1024 * 1024
REGISTRATIONS_FILE = "alm_ledgers.json"
LIFECYCLE_KINDS = {"configuration", "evaluation", "proposal", "review", "release", "deployment"}
NAMESPACE = "_dncp_verified_alm_lifecycle"
INSTALL_GUIDANCE = (
    'Install with authenticated private repository access: pip install "devnet-control-plane[alm]", '
    "or offline with install_alm_core.py and the digest-pinned producer wheel. "
    f"Required alm-lifecycle-core=={ALM_VERSION} at commit {ALM_COMMIT}."
)
NOTICE = (
    "Structural validation only. Ledger records, evaluations, reviews and deployments are "
    "recorded assertions, not authenticated attestations, observed behavior or live state. "
    "Nothing was imported, copied, installed, promoted or executed, and no component is trusted."
)


class AlmExchangeError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


_core: Any = None


def require_alm_core() -> Any:
    """Load the pinned lifecycle core from its verified, distribution-owned sources."""
    global _core
    with SNAPSHOT_LOAD_LOCK:
        if _core is not None:
            return _core
        try:
            sources = _prepare_owned(
                "alm-lifecycle-core", ALM_VERSION, ALM_COMMIT, ALM_URL, ALM_WHEEL_SHA256,
                "alm_lifecycle", ("__init__", "lifecycle"),
            )
            core = load_package_from_snapshot("alm_lifecycle", NAMESPACE, sources)
            if core.__version__ != ALM_VERSION:
                raise ValueError("module version mismatch")
        except PackageNotFoundError:
            raise AlmExchangeError(
                "capability_missing", "ALM lifecycle core is not installed. " + INSTALL_GUIDANCE, 503,
            ) from None
        except (ValueError, OSError, ImportError, SyntaxError, AttributeError, TypeError, KeyError):
            unload_package_snapshot(NAMESPACE)
            raise AlmExchangeError(
                "capability_unverified",
                f"DNCP requires alm-lifecycle-core=={ALM_VERSION} with verified source provenance. "
                + INSTALL_GUIDANCE, 503,
            ) from None
        _core = core
        return core


def clear_alm_core_cache() -> None:
    global _core
    with SNAPSHOT_LOAD_LOCK:
        _core = None
        unload_package_snapshot(NAMESPACE)


def _component(registry: Any, record: dict[str, Any]) -> dict[str, Any]:
    inspection = registry.inspect(record)
    return {
        "id": record["id"], "kind": record["kind"], "version": record["version"],
        "revision": record["revision"], "upstream_refs": record["upstream_refs"],
        "origin": record["origin"], "dependencies": record["dependencies"],
        # File content stays in the ledger; only its path and digest are reported.
        "files": [{"path": item["path"], "sha256": item["sha256"]} for item in record["files"]],
        "used_by": inspection["used_by"],
    }


def _evaluated_uses(registry: Any, record: dict[str, Any]) -> list[dict[str, Any]]:
    inspection = registry.inspect(record)
    subjects = [record] + [registry.resolve(pin) for pin in inspection["used_by"]]
    result = []
    for subject in subjects:
        if subject is not record and subject["kind"] != "configuration":
            continue
        evaluations = []
        for pin in registry.inspect(subject)["evaluations"]:
            evidence = registry.resolve(pin)
            evaluations.append({**pin, "mode": evidence["mode"], "dataset": evidence["dataset"],
                                "outcomes": dict(Counter(case["outcome"] for case in evidence["cases"])),
                                "failed_cases": [case["id"] for case in evidence["cases"] if case["outcome"] == "fail"]})
        result.append({"id": subject["id"], "revision": subject["revision"], "kind": subject["kind"],
                       "evaluations": evaluations})
    return result


def _read_registry(manifest: Path, root: Path | None = None) -> tuple[Any, bytes]:
    """Read and validate one ledger with the pinned core; raises AlmExchangeError."""
    core = require_alm_core()
    try:
        size = manifest.stat().st_size
        if not manifest.is_file() or size > MAX_MANIFEST_BYTES:
            raise AlmExchangeError("unavailable", "Ledger is not a regular file of at most 16 MiB.")
        raw = manifest.read_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise AlmExchangeError("unavailable", "Ledger is not a regular file of at most 16 MiB.")
        if root is not None and not root.is_dir():
            raise AlmExchangeError("unavailable", "Workspace root is not a directory.")
    except OSError:
        raise AlmExchangeError("unavailable", "Ledger is unavailable or unreadable.", 503) from None
    try:
        registry = core.LifecycleRegistry(core.read_json_bytes(raw), root)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        # The core's messages name record IDs, fields and relative paths, never file content.
        detail = str(exc)[:300] if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else "malformed ledger"
        raise AlmExchangeError("ledger_invalid", f"Ledger failed validation: {detail}") from None
    except OSError:
        raise AlmExchangeError("ledger_invalid", "Ledger failed validation: a recorded file is missing under the root.") from None
    return registry, raw


def inspect_ledger(manifest: Path, root: Path | None = None, kind: str = "", component_id: str = "") -> dict[str, Any]:
    """Validate one ledger and summarize its components and release readiness without trusting it.

    With `root`, every recorded file digest is also compared with the file under that
    directory, so drift is a validation failure. Only component metadata is returned.
    """
    registry, raw = _read_registry(manifest, root)
    records = list(registry.records.values())
    component_kinds = sorted({r["kind"] for r in records} - LIFECYCLE_KINDS)
    if kind and kind not in component_kinds:
        raise AlmExchangeError("not_found", "No component of that kind is in the ledger.", 404)
    selected = [r for r in records if r["kind"] in component_kinds
                and (not kind or r["kind"] == kind) and (not component_id or r["id"] == component_id)]
    if component_id and not selected:
        raise AlmExchangeError("not_found", "No component with that ID is in the ledger.", 404)
    selected.sort(key=lambda r: (r["kind"], r["id"], r["version"]))
    releases = []
    for record in sorted((r for r in records if r["kind"] == "release"), key=lambda r: (r["id"], r["version"])):
        readiness = registry.readiness(record)
        releases.append({
            "id": record["id"], "version": record["version"], "revision": record["revision"],
            "product": record["product"],
            "ready_for_human_release_decision": readiness["ready_for_human_release_decision"],
            "blockers": readiness["blockers"],
        })
    return {
        "mode": "read-only-alm-ledger-inspection",
        "contract": {"registry": registry.manifest["registry"], "schema_version": registry.manifest["schema_version"],
                     "owner": registry.manifest["owner"]},
        "validator": {"package": "alm-lifecycle-core", "version": ALM_VERSION, "commit": ALM_COMMIT},
        "ledger": {"sha256": hashlib.sha256(raw).hexdigest(), "entries": len(records),
                   "kinds": dict(sorted(Counter(r["kind"] for r in records).items()))},
        "valid": True, "trusted": False, "files_compared_with_root": root is not None,
        "live_deployment_verified": False,
        "components": [{**_component(registry, record), "evaluated_uses": _evaluated_uses(registry, record)}
                       for record in selected],
        "releases": releases,
        "notice": NOTICE,
    }


# --- Explicitly registered ledgers, read at query time (no cache) ---------------------------


def _registrations(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / REGISTRATIONS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["ledgers"]
        if data.get("schema_version") != 1 or not isinstance(entries, list) or len(entries) > MAX_LEDGERS:
            raise ValueError
        for entry in entries:
            if (set(entry) != {"manifest", "root", "enabled", "registered_at"}
                    or not isinstance(entry["manifest"], str) or type(entry["enabled"]) is not bool
                    or not (entry["root"] is None or isinstance(entry["root"], str))):
                raise ValueError
        return entries
    except (OSError, ValueError, KeyError, TypeError):
        raise AlmExchangeError("registrations_invalid", "ALM ledger registrations are unreadable or malformed.", 503) from None


def _save(data_dir: Path, entries: list[dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / REGISTRATIONS_FILE
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"schema_version": 1, "ledgers": entries}, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def list_ledgers(data_dir: Path) -> dict[str, Any]:
    return {"schema_version": 1, "ledgers": _registrations(data_dir)}


def register_ledger(data_dir: Path, manifest: Path, root: Path | None = None) -> dict[str, Any]:
    """Record an explicit ledger path (and optional checkout root) after it validates.

    Registration stores two paths only. It copies nothing from the ledger and grants no trust.
    """
    manifest = manifest.resolve()
    root = root.resolve() if root is not None else None
    registry, raw = _read_registry(manifest)
    if root is not None and not root.is_dir():
        raise AlmExchangeError("unavailable", "Workspace root is not a directory.")
    entries = [entry for entry in _registrations(data_dir) if entry["manifest"] != str(manifest)]
    if len(entries) >= MAX_LEDGERS:
        raise AlmExchangeError("limit", f"At most {MAX_LEDGERS} ledgers can be registered.")
    entry = {"manifest": str(manifest), "root": str(root) if root is not None else None, "enabled": True,
             "registered_at": datetime.now(timezone.utc).isoformat()}
    _save(data_dir, entries + [entry])
    return {"registered": entry, "ledger": {"sha256": hashlib.sha256(raw).hexdigest(), "entries": len(registry.records)},
            "trusted": False, "notice": NOTICE}


def disable_ledger(data_dir: Path, manifest: Path) -> dict[str, Any]:
    manifest = manifest.resolve()
    entries = _registrations(data_dir)
    matches = [entry for entry in entries if entry["manifest"] == str(manifest)]
    if not matches:
        raise AlmExchangeError("not_found", "That ledger is not registered.", 404)
    matches[0]["enabled"] = False
    _save(data_dir, entries)
    return {"disabled": matches[0]}


def _workspace_state(root: Path | None, name: str, expected: str) -> str:
    """Compare one recorded digest with the file under the registered root, without raising."""
    if root is None:
        return "not_compared"
    relative = Path(*name.split("/"))
    try:
        target = (root / relative).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            return "missing"
        if target.stat().st_size > MAX_COMPARED_FILE_BYTES:
            return "changed"
        return "match" if hashlib.sha256(target.read_bytes()).hexdigest() == expected else "changed"
    except OSError:
        return "missing"


def component_ref(record: dict[str, Any]) -> str:
    """Stable citation `alm:<id>@<version>`; IDs that already carry the prefix are not doubled."""
    identity = record["id"] if record["id"].startswith("alm:") else "alm:" + record["id"]
    return f"{identity}@{record['version']}"


def ledger_components(data_dir: Path, query: str = "", limit: int = 20, *,
                      match_content: bool = True) -> dict[str, Any]:
    """Components of every enabled registered ledger, matched lexically against `query`.

    Ledgers are read and validated on each call. A ledger that fails is reported, not
    raised, so one bad file does not hide the others. File content is matched (unless
    `match_content` is false) but never returned. Relevance is not suitability, and nothing
    here is trusted.
    """
    registered = _registrations(data_dir)
    enabled = [entry for entry in registered if entry["enabled"]]
    tokens = [token for token in re.findall(r"[a-z0-9_]+", query.lower()) if len(token) >= 2]
    ledgers: list[dict[str, Any]] = []
    scored: list[tuple[int, str, str, dict[str, Any]]] = []
    for entry in enabled:
        manifest = Path(entry["manifest"])
        root = Path(entry["root"]) if entry["root"] else None
        try:
            registry, raw = _read_registry(manifest)
        except AlmExchangeError as exc:
            ledgers.append({"manifest": entry["manifest"], "root": entry["root"], "status": "failed", "code": exc.code})
            continue
        ledger_digest = hashlib.sha256(raw).hexdigest()
        root_available = root is not None and root.is_dir()
        drifted = 0
        for record in registry.records.values():
            if record["kind"] in LIFECYCLE_KINDS:
                continue
            files = [{"path": item["path"], "sha256": item["sha256"],
                      "workspace": _workspace_state(root if root_available else None, item["path"], item["sha256"])}
                     for item in record["files"]]
            states = {item["workspace"] for item in files}
            drift = None if states == {"not_compared"} else bool(states & {"changed", "missing"})
            drifted += bool(drift)
            name = record["id"].lower()
            blob = " ".join([record["kind"], record["origin"]["repository"], record["origin"]["locator"],
                             *(item["path"] for item in record["files"]),
                             *((item["content"] for item in record["files"]) if match_content else ())]).lower()
            score = sum(5 if token in name else 2 if token in blob else 0 for token in tokens) if tokens else 1
            if score:
                scored.append((-score, record["id"], record["version"], {
                    "id": record["id"], "category": "alm_component", "kind": record["kind"],
                    "version": record["version"], "revision": record["revision"],
                    "ref": component_ref(record),
                    "origin": record["origin"], "dependencies": record["dependencies"], "files": files,
                    "workspace_drift": drift, "ledger_sha256": ledger_digest, "manifest": entry["manifest"],
                    "trusted": False,
                    "evaluated_uses": _evaluated_uses(registry, record),
                }))
        ledgers.append({"manifest": entry["manifest"], "root": entry["root"], "status": "read",
                        "sha256": ledger_digest, "entries": len(registry.records),
                        "root_compared": root_available, "components_with_drift": drifted})
    scored.sort(key=lambda item: item[:3])
    return {"registered": len(registered), "enabled": len(enabled), "ledgers": ledgers,
            "total": len(scored), "components": [item[3] for item in scored[:limit]], "notice": NOTICE}
