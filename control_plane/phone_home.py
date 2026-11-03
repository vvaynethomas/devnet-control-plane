"""Local reuse checks and provisional intake, never a canonical knowledge store."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from . import DEFAULT_DATA_DIR, DEV_NETWORK_ROOT, FACTORY_ROOT, PROJECT_ROOT
from .capabilities import discover_capabilities, scan_network_modules
from .fabric import FabricIndex, SECRET_RE, collect_knowledge_entities

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESULTS = 50
KINDS = ("discovery", "tool", "skill", "runbook", "module", "finding", "decision")
NOTICE = "Ingested locally as provisional evidence, not canonical knowledge. No second acceptance; only a human approves consequential execution, adoption or canonical promotion."


class PhoneHomeError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_field(value: Any, name: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise PhoneHomeError(f"{name} must be {'a nonempty' if required else 'a'} string of at most {maximum} characters")
    if SECRET_RE.search(value):
        raise PhoneHomeError(f"{name} contains a recognized credential pattern; remove sensitive material")
    return value.strip()


def result_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RESULTS:
        raise PhoneHomeError(f"limit must be an integer from 1 to {MAX_RESULTS}")
    return value


def validate_submission(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PhoneHomeError("submission must be a JSON object")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise PhoneHomeError("submission exceeds 64 KiB", 413)
    if payload.get("kind") == "material":
        from .material_ingestion import MaterialError, digest_submission
        try:
            return digest_submission(payload)
        except MaterialError as exc:
            setattr(exc, "status", 400)
            raise
    allowed = {"schema_version", "kind", "title", "summary", "source_repo", "reuse_query",
               "source_session", "source_ref", "related_refs", "tags", "idempotency_key", "external_evidence"}
    if set(payload) - allowed:
        raise PhoneHomeError("unknown submission fields")
    version = payload.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise PhoneHomeError("schema_version must be 1")
    if payload.get("kind") not in KINDS:
        raise PhoneHomeError("unsupported submission kind")
    clean: dict[str, Any] = {"schema_version": 1, "kind": payload["kind"]}
    for field, maximum in (("title", 200), ("summary", 20000), ("source_repo", 1000), ("reuse_query", 2000)):
        clean[field] = text_field(payload.get(field), field, maximum)
    for field in ("source_session", "source_ref", "idempotency_key"):
        clean[field] = text_field(payload.get(field, ""), field, 1000, required=False)
    clean["external_evidence"] = text_field(payload.get("external_evidence", ""), "external_evidence", 20000, required=False)
    for field in ("related_refs", "tags"):
        values = payload.get(field, [])
        if not isinstance(values, list) or len(values) > 20:
            raise PhoneHomeError(f"{field} must be an array of at most 20 strings")
        clean[field] = [text_field(v, field, 200) for v in values]
    return clean


class PhoneHome:
    def __init__(
        self, factory_root: Path = FACTORY_ROOT, network_root: Path = DEV_NETWORK_ROOT,
        data_dir: Path = DEFAULT_DATA_DIR, fabric: FabricIndex | None = None,
    ) -> None:
        self.factory_root = factory_root.resolve()
        self.network_root = network_root.resolve()
        self.data_dir = data_dir.resolve()
        for protected in (self.factory_root, PROJECT_ROOT.resolve()):
            if self.data_dir == protected or protected in self.data_dir.parents:
                raise PhoneHomeError("phone-home data directory must be outside source repositories")
        # Protect any Git checkout containing an explicitly configured inbox.
        for ancestor in (self.data_dir, *self.data_dir.parents):
            if (ancestor / ".git").exists():
                raise PhoneHomeError("phone-home data directory must be outside Git repositories")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "phone_home.sqlite"
        self.fabric = fabric or FabricIndex(self.data_dir / "control_plane_fabric.sqlite", self.factory_root)
        with closing(self._connect()) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY, submitted_at TEXT NOT NULL, digest TEXT NOT NULL,
                idempotency_key TEXT UNIQUE, payload TEXT NOT NULL)"""
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _receipt(row: sqlite3.Row) -> dict[str, Any]:
        return {**json.loads(row["payload"]), "id": row["id"], "submitted_at": row["submitted_at"],
                "content_digest": row["digest"], "status": "provisional", "notice": NOTICE}

    def submit(self, payload: Any) -> dict[str, Any]:
        clean = validate_submission(payload)
        encoded = json.dumps(clean, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        key = clean["idempotency_key"] or None
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if key:
                existing = conn.execute("SELECT * FROM submissions WHERE idempotency_key=?", (key,)).fetchone()
                if existing is not None:
                    if existing["digest"] != digest:
                        raise PhoneHomeError("idempotency_key already used with different content", 409)
                    return self._receipt(existing)
            sid = f"INTAKE-{uuid.uuid4()}"
            conn.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?)", (sid, utc_now(), digest, key, encoded))
            row = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
            conn.commit()
        assert row is not None
        return self._receipt(row)

    def get(self, submission_id: str) -> dict[str, Any]:
        sid = text_field(submission_id, "id", 100)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise PhoneHomeError("submission not found", 404)
        return self._receipt(row)

    def list(self, query: str = "", limit: int = 20, offset: int = 0) -> dict[str, Any]:
        q = text_field(query, "query", 2000, required=False)
        limit = result_limit(limit)
        if type(offset) is not int or offset < 0:
            raise PhoneHomeError("offset must be a nonnegative integer")
        # Literal substring search; never interpret caller input as SQL or wildcards.
        with closing(self._connect()) as conn:
            count = conn.execute("SELECT count(*) FROM submissions WHERE instr(lower(payload),lower(?))>0", (q,)).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM submissions WHERE instr(lower(payload),lower(?))>0 ORDER BY submitted_at DESC, id LIMIT ? OFFSET ?",
                (q, limit, offset),
            ).fetchall()
        return {"schema_version": 1, "notice": NOTICE, "total": count, "offset": offset,
                "next_offset": offset + limit if offset + limit < count else None,
                "submissions": [self._receipt(row) for row in rows]}

    def check(self, query: str, limit: int = 20) -> dict[str, Any]:
        q = text_field(query, "query", 2000)
        limit = result_limit(limit)
        warnings = [
            "Text relevance is not readiness or approval; absence does not prove no reusable capability exists.",
            "Conversation coverage is partial: imported chats and VS Code chats are not in Fabric; no watcher or export parser.",
        ]
        canonical_available = self.factory_root.is_dir()
        if not canonical_available:
            warnings.append(f"Canonical source directory unavailable: {self.factory_root}")
        # Existing collectors skip malformed registries; make that limitation visible.
        for name in ("skill", "prompt", "runbook", "project"):
            registry = self.factory_root / "cockpit" / f"{name}-registry.json"
            if not registry.is_file():
                warnings.append(f"Registry unavailable: {registry}")
                continue
            try:
                data = json.loads(registry.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
                    raise ValueError("expected entries array")
                if any(not isinstance(e, dict) or not isinstance(e.get("id"), str)
                       or not isinstance(e.get("title"), str) or not isinstance(e.get("path", ""), str)
                       for e in data["entries"]):
                    raise ValueError("entries require string id/title/path")
            except (OSError, ValueError) as exc:
                warnings.append(f"Registry unreadable or invalid: {registry}: {exc}")
        before = self.fabric.freshness()
        if before["factory_root"] and before["factory_root"] != str(self.factory_root):
            raise PhoneHomeError("Fabric cache belongs to another canonical root; rebuild explicitly with the intended configuration", 503)
        try:
            if not before["built"]:
                if canonical_available:
                    self.fabric.rebuild(include_conversations=False)
                    warnings.append("Initialized canonical-only Fabric cache for this check; no personal chat harvest.")
                else:
                    warnings.append("No Fabric cache available.")
            # Current reads detect source failures even when search uses a cache.
            entities = collect_knowledge_entities(self.factory_root) if canonical_available else {}
            capabilities = discover_capabilities(
                q, self.factory_root, self.fabric if self.fabric.freshness()["built"] else None,
                include_modules=False,
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            canonical_available = False
            entities = {}
            capabilities = {"existing_tools_and_modules": [], "related_patterns": [], "have_we_solved_this_before": []}
            warnings.append(f"Canonical capability read failed: {exc}")
        modules, module_coverage, module_warnings = scan_network_modules(self.factory_root, self.network_root, q)
        warnings.extend(module_warnings)
        tools = capabilities["existing_tools_and_modules"]
        for item in tools:
            item["status"] = entities.get(item["id"], {}).get("status", item.get("status", "unverified"))
            item["abs_path"] = str((self.factory_root / item["path"]).resolve()) if isinstance(item["path"], str) and item["path"] else ""
            item["source_available"] = bool(item["abs_path"] and Path(item["abs_path"]).is_file())
        for item in capabilities["related_patterns"]:
            entity = entities.get(item["id"], {})
            item["status"] = entity.get("status", "unverified")
            item["upstream_refs"] = entity.get("upstream_refs", [])
            item["downstream_refs"] = entity.get("downstream_refs", [])
            item["abs_path"] = entity.get("abs_path", "")
            item["source_available"] = bool(item["abs_path"] and Path(item["abs_path"]).is_file())
        for item in capabilities["have_we_solved_this_before"]:
            item["source_available"] = bool(item["abs_path"] and Path(item["abs_path"]).is_file())
        if any(not item["source_available"] for item in
               tools + capabilities["related_patterns"] + capabilities["have_we_solved_this_before"]):
            warnings.append("Some matched source files are unavailable; registry/cache entries alone do not establish access.")
        freshness = self.fabric.freshness()
        if freshness["built"] and not freshness["rebuilt_at"]:
            warnings.append("Legacy Fabric cache freshness is unknown; rebuild explicitly.")
        reusable = tools + modules + capabilities["related_patterns"] + capabilities["have_we_solved_this_before"]
        # Conversation mentions and provisional intake alone are not evidence of a reusable capability.
        candidates = [r for r in reusable if r.get("kind") != "conversation"
                      and r.get("source_available", True) and (r.get("abs_path") or r.get("path"))][:limit]
        owners: list[dict[str, Any]] = []
        registry = self.factory_root / "cockpit" / "project-registry.json"
        if registry.is_file():
            try:
                registered = json.loads(registry.read_text(encoding="utf-8"))
                for entry in registered["entries"]:
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("title"), str):
                        owners.append({"id": entry["id"], "title": entry["title"], "path": entry.get("path", ""),
                                       "status": entry.get("status", "unverified"), "fit": "not evaluated"})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f"Candidate owner registry unavailable: {exc}")
        ladder = {
            "ordered": True, "stopped_at": 1 if candidates else 2, "human_final_choice": True,
            "recommendation": "Review cited network capability for reuse with customization." if candidates
                              else "Resolve the battle-tested external solution/component check before choosing ownership.",
            "steps": [
                {"step": 1, "name": "Existing network capability: reuse with customization",
                 "status": "candidate evidence; suitability requires human review" if candidates else "no match in covered sources; absence unproven",
                 "evidence": candidates},
                {"step": 2, "name": "Battle-tested external solution or component",
                 "status": "not reached" if candidates else "unresolved",
                 "external_check": "external check not performed",
                 "unknowns": ["No live external research in this slice. Record source and evaluation in external_evidence intake.",
                              "Provisional reports do not prove battle-tested suitability or approval."]},
                {"step": 3, "name": "Extension or new capability in an existing product",
                 "status": "not reached; earlier steps must be resolved",
                 "candidate_owners": owners[:limit]},
                {"step": 4, "name": "Standalone product",
                 "status": "not recommended; justification not established",
                 "criteria": ["Earlier reuse/component checks resolved with evidence.",
                              "No suitable existing product owner, with an explained boundary.",
                              "Independent value serving the network and/or users outside it.",
                              "Human approves standalone ownership and maintenance."]},
            ],
        }
        return {
            "schema_version": 1, "query": q, "checked_at": utc_now(), "mode": "read-only-advisory",
            "coverage": {"canonical_available": canonical_available, "factory_root": str(self.factory_root),
                         "network_root": str(self.network_root), "fabric": freshness, "modules": module_coverage,
                         "complete_network_inventory": False},
            "warnings": warnings,
            "decision_ladder": ladder,
            "existing_tools_and_modules": (tools + modules)[:limit],
            "related_patterns": capabilities["related_patterns"][:limit],
            "prior_findings_and_decisions": capabilities["have_we_solved_this_before"][:limit],
            "provisional_intake": self.list(q, limit),
        }
