"""Read-only inspection of an explicitly selected ALM lifecycle ledger (DNCP-012).

Validation is done by the pinned, provenance-checked `alm-lifecycle-core`; DNCP adds no
second validator. Nothing is imported into DNCP, copied, installed, promoted or executed,
and a valid ledger is never reported as trusted: its evaluations and approvals are
recorded assertions.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

from .material_capability import _prepare_owned
from .material_pins import ALM_COMMIT, ALM_URL, ALM_VERSION, ALM_WHEEL_SHA256
from .verified_package import SNAPSHOT_LOAD_LOCK, load_package_from_snapshot, unload_package_snapshot

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
NAMESPACE = "_dncp_verified_alm_lifecycle"
INSTALL_GUIDANCE = (
    'Install with authenticated private repository access: pip install "devnet-control-plane[alm]". '
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


def _component(registry: Any, core: Any, record: dict[str, Any]) -> dict[str, Any]:
    used_by = registry.inspect(record)["used_by"]
    return {
        "id": record["id"], "kind": record["kind"], "version": record["version"],
        "revision": record["revision"], "upstream_refs": record["upstream_refs"],
        "origin": record["origin"], "dependencies": record["dependencies"],
        # File content stays in the ledger; only its path and digest are reported.
        "files": [{"path": item["path"], "sha256": item["sha256"]} for item in record["files"]],
        "used_by": used_by,
    }


def inspect_ledger(manifest: Path, root: Path | None = None, kind: str = "", component_id: str = "") -> dict[str, Any]:
    """Validate one ledger and summarize its components and release readiness without trusting it.

    With `root`, every recorded file digest is also compared with the file under that
    directory, so drift is a validation failure. Only component metadata is returned.
    """
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

    records = list(registry.records.values())
    component_kinds = sorted({r["kind"] for r in records} - {
        "configuration", "evaluation", "proposal", "review", "release", "deployment"})
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
        "components": [_component(registry, core, record) for record in selected],
        "releases": releases,
        "notice": NOTICE,
    }
