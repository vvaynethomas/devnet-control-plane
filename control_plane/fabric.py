"""Pillar 3: Knowledge & Conversation Fabric (SQLite FTS5 unified search & provenance graph)."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import DEFAULT_DATA_DIR, FACTORY_ROOT
from .safety import SECRET_RE
from .conversation_library import ConversationLibraryError, _configured_hub_api
from .conversation_hub_adapter import read_local_sessions

ID_RE = re.compile(r"\b(SRC|FND|PAT|DEC|PRM|WF|RUN|SKL|PRJ|ART|BL)-\d{4}\b")
logger = logging.getLogger(__name__)


def redact_secrets(text: str) -> str:
    """Redact token-like strings from indexed/displayed conversation excerpts (DEC-0004)."""
    if not text:
        return ""
    return SECRET_RE.sub("[REDACTED_SECRET]", text)


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
    if end is None:
        return {}, text
    fm: dict[str, Any] = {}
    for line in lines[1:end]:
        k, _, v = line.partition(":")
        v = v.split(" #")[0].strip()
        if v.startswith("[") and v.endswith("]"):
            fm[k.strip()] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k.strip()] = v.strip("\"'")
    body = "\n".join(lines[end + 1 :]).strip()
    return fm, body


def collect_knowledge_entities(factory_root: Path = FACTORY_ROOT) -> dict[str, dict[str, Any]]:
    """Collect all canonical markdown & registry entities with full upstream/downstream provenance."""
    entities: dict[str, dict[str, Any]] = {}

    md_paths: list[Path] = []
    if (factory_root / "knowledge").is_dir():
        md_paths.extend(p for p in (factory_root / "knowledge").rglob("*.md") if p.name != "README.md")
    if (factory_root / "projects").is_dir():
        md_paths.extend(sorted((factory_root / "projects").glob("*/README.md")))
        md_paths.extend(sorted((factory_root / "projects").glob("*/artifacts/*.md")))
    for folder in ("workflows", "runbooks"):
        if (factory_root / folder).is_dir():
            md_paths.extend(p for p in (factory_root / folder).glob("*.md") if p.name != "README.md")

    for path in md_paths:
        fm, body = _parse_frontmatter(path)
        eid = fm.get("id")
        if not eid:
            continue
        rel = path.relative_to(factory_root).as_posix()
        mentioned = sorted(set(m.group(0) for m in ID_RE.finditer(body)) - {eid})
        entities[eid] = {
            "id": eid,
            "title": fm.get("title", path.stem),
            "kind": fm.get("type", "record"),
            "status": fm.get("status", "draft"),
            "created_date": fm.get("created_date", ""),
            "tags": fm.get("tags", []),
            "path": rel,
            "abs_path": str(path.resolve()),
            "upstream_refs": fm.get("upstream_refs") if isinstance(fm.get("upstream_refs"), list) else [],
            "downstream_refs": fm.get("downstream_refs") if isinstance(fm.get("downstream_refs"), list) else [],
            "mentioned_ids": mentioned,
            "body": body,
        }

    # Add skills and prompts from cockpit registries
    for reg_file in ("skill-registry.json", "prompt-registry.json"):
        reg_path = factory_root / "cockpit" / reg_file
        if not reg_path.is_file():
            continue
        try:
            reg_data = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in reg_data.get("entries", []):
            eid = entry.get("id")
            if not eid or eid in entities:
                continue
            rel = entry.get("path", "")
            full_path = factory_root / rel if rel else None
            body = (
                full_path.read_text(encoding="utf-8", errors="replace")
                if full_path and full_path.is_file()
                else f"{entry.get('input_schema', '')}\n{entry.get('output_schema', '')}"
            )
            mentioned = sorted(set(m.group(0) for m in ID_RE.finditer(body)) - {eid})
            entities[eid] = {
                "id": eid,
                "title": entry.get("title", eid),
                "kind": entry.get("type", "operational"),
                "status": entry.get("status", "draft"),
                "created_date": (entry.get("promotion_metrics") or {}).get("last_executed") or "",
                "path": rel,
                "abs_path": str(full_path.resolve()) if full_path and full_path.is_file() else "",
                "upstream_refs": entry.get("upstream_refs", []),
                "downstream_refs": entry.get("downstream_refs", []),
                "mentioned_ids": mentioned,
                "body": body,
            }

    return entities


def _harvest_antigravity_sessions(max_sessions: int = 20) -> list[dict[str, Any]]:
    """Read-only harvest of local Antigravity conversation transcripts (`~/.gemini/antigravity/brain`)."""
    brain_root = Path(os.path.expanduser("~")) / ".gemini" / "antigravity" / "brain"
    records: list[dict[str, Any]] = []
    if not brain_root.is_dir():
        return records
    try:
        sessions, diagnostics, _ = read_local_sessions(
            "antigravity",
            brain_root,
            archive_key="dncp-local-antigravity",
            max_sessions=max_sessions,
            selection_policy="directory-first",
        )
    except ConversationLibraryError as exc:
        if exc.code != "hub_unavailable":
            raise
        logger.warning(
            "Optional Conversation Hub is not installed; Fabric uses its legacy Antigravity reader. "
            "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.4 adapter."
        )
        sessions = None
        diagnostics = []
    except (ValueError, OSError) as exc:
        logger.warning("Conversation Hub could not read the selected Antigravity source (%s).", type(exc).__name__)
        return records
    if sessions is not None:
        for item in diagnostics:
            logger.warning("Antigravity Fabric source adapter: %s", item)
        for session in sessions:
            user_turns = [
                redact_secrets(turn["user_prompt"][:1200])
                for turn in session["turns"]
                if turn["user_prompt"]
            ]
            assistant_turns = [
                redact_secrets(text[:1200])
                for turn in session["turns"]
                for text in turn["assistant_responses"]
                if text
            ]
            assistant_turns.extend(
                redact_secrets(message["content"][:1200])
                for message in session["unassigned_messages"]
                if message["role"] == "assistant" and message["content"]
            )
            combined = "\n\n---\n\n".join(
                [f"[USER]: {text}" for text in user_turns[:8]]
                + [f"[ASSISTANT]: {text}" for text in assistant_turns[:6]]
            )
            if not combined:
                continue
            mentioned = sorted(set(match.group(0) for match in ID_RE.finditer(combined)))
            first_prompt = user_turns[0][:110].replace("\n", " ") if user_turns else (
                f"Session {session['full_session_id'][:8]}"
            )
            records.append({
                "id": f"CHAT-AGY-{session['full_session_id'][:8]}",
                "title": f"Antigravity Session: {first_prompt}",
                "kind": "conversation",
                "harness": "antigravity",
                "status": f"{len(user_turns)} user turns",
                "created_date": session["created_date"],
                "path": f"conversation://{session['full_session_id']}",
                "abs_path": session["source_path"],
                "upstream_refs": mentioned[:6],
                "downstream_refs": [],
                "mentioned_ids": mentioned,
                "body": combined,
            })
        return records

    session_dirs = sorted(
        [d for d in brain_root.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:max_sessions]
    for sdir in session_dirs:
        transcript = sdir / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.is_file():
            continue
        session_id = sdir.name
        user_turns: list[str] = []
        assistant_turns: list[str] = []
        created_at = ""
        try:
            for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if not created_at and obj.get("created_at"):
                    created_at = str(obj["created_at"])[:19]
                step_type = obj.get("type", "")
                content = str(obj.get("content") or "").strip()
                if not content:
                    continue
                if step_type == "USER_INPUT":
                    clean = re.sub(r"</?USER_REQUEST>", "", content).strip()
                    if clean:
                        user_turns.append(redact_secrets(clean[:1200]))
                elif step_type == "PLANNER_RESPONSE":
                    assistant_turns.append(redact_secrets(content[:1200]))
        except Exception:
            continue
        if not user_turns and not assistant_turns:
            continue
        first_prompt = user_turns[0][:110].replace("\n", " ") if user_turns else f"Session {session_id[:8]}"
        combined = "\n\n---\n\n".join(
            [f"[USER]: {u}" for u in user_turns[:8]] + [f"[ASSISTANT]: {a}" for a in assistant_turns[:6]]
        )
        mentioned = sorted(set(m.group(0) for m in ID_RE.finditer(combined)))
        records.append(
            {
                "id": f"CHAT-AGY-{session_id[:8]}",
                "title": f"Antigravity Session: {first_prompt}",
                "kind": "conversation",
                "harness": "antigravity",
                "status": f"{len(user_turns)} user turns",
                "created_date": created_at,
                "path": f"conversation://{session_id}",
                "abs_path": str(transcript.resolve()),
                "upstream_refs": mentioned[:6],
                "downstream_refs": [],
                "mentioned_ids": mentioned,
                "body": combined,
            }
        )
    return records


def _harvest_copilot_sessions(max_sessions: int = 25) -> list[dict[str, Any]]:
    """Read-only harvest of local Copilot CLI / App session logs (`~/.copilot/session-state`)."""
    copilot_root = Path(os.path.expanduser("~")) / ".copilot" / "session-state"
    records: list[dict[str, Any]] = []
    if not copilot_root.is_dir():
        return records
    try:
        sessions, diagnostics, _ = read_local_sessions(
            "copilot-cli", copilot_root,
            archive_key="dncp-local-copilot-cli", max_sessions=max_sessions,
        )
    except ConversationLibraryError as exc:
        if exc.code != "hub_unavailable":
            raise
        else:
            logger.warning(
                "Optional Conversation Hub is not installed; Fabric uses its legacy Copilot CLI reader. "
                "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.4 adapter."
            )
        sessions = None
        diagnostics = []
    except (ValueError, OSError) as exc:
        logger.warning(
            "Conversation Hub could not read the selected Copilot CLI source (%s).",
            type(exc).__name__,
        )
        return records
    if sessions is not None:
        for item in diagnostics:
            logger.warning("Copilot CLI source adapter: %s", item)
        for session in sessions:
            snippets: list[str] = []
            for turn in session["turns"]:
                snippets.extend(
                    [turn["user_prompt"]]
                    + turn["assistant_responses"]
                    + [
                        message["content"]
                        for message in turn.get("other_messages", [])
                    ]
                )
            snippets.extend(
                message["content"] for message in session.get("unassigned_messages", [])
            )
            snippets = [text for text in snippets if isinstance(text, str) and len(text.strip()) > 15]
            if not snippets:
                continue
            combined = "\n\n".join(snippets[:12])
            mentioned = sorted(set(match.group(0) for match in ID_RE.finditer(combined)))
            records.append({
                "id": f"CHAT-COP-{session['full_session_id'][:8]}",
                "title": f"Copilot Session: {snippets[0][:90].replace(chr(10), ' ')}",
                "kind": "conversation",
                "harness": "copilot-cli",
                "status": f"{len(snippets)} events",
                "created_date": session["created_date"],
                "path": session["source_path"],
                "abs_path": session["source_path"],
                "upstream_refs": mentioned[:6],
                "downstream_refs": [],
                "mentioned_ids": mentioned,
                "body": combined,
            })
        return records

    event_files = sorted(
        copilot_root.glob("*/events.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_sessions]
    for ev_file in event_files:
        session_id = ev_file.parent.name
        snippets: list[str] = []
        created_at = ""
        try:
            for line in ev_file.read_text(encoding="utf-8", errors="replace").splitlines()[:120]:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if not created_at and obj.get("timestamp"):
                    created_at = str(obj["timestamp"])[:19]
                msg = obj.get("message") or obj.get("content") or obj.get("text") or ""
                if isinstance(msg, dict):
                    msg = json.dumps(msg)
                if isinstance(msg, str) and len(msg.strip()) > 15:
                    snippets.append(redact_secrets(msg.strip()[:800]))
        except Exception:
            continue
        if not snippets:
            continue
        combined = "\n\n".join(snippets[:12])
        mentioned = sorted(set(m.group(0) for m in ID_RE.finditer(combined)))
        records.append(
            {
                "id": f"CHAT-COP-{session_id[:8]}",
                "title": f"Copilot Session: {snippets[0][:90].replace(chr(10), ' ')}",
                "kind": "conversation",
                "harness": "copilot-cli",
                "status": f"{len(snippets)} events",
                "created_date": created_at,
                "path": str(ev_file),
                "abs_path": str(ev_file.resolve()),
                "upstream_refs": mentioned[:6],
                "downstream_refs": [],
                "mentioned_ids": mentioned,
                "body": combined,
            }
        )
    return records


class FabricIndex:
    """Rebuildable SQLite FTS5 index over Factory knowledge entities and AI conversations (PAT-0003)."""

    def __init__(self, db_path: Path | None = None, factory_root: Path = FACTORY_ROOT) -> None:
        self.factory_root = factory_root
        self.db_path = db_path or (DEFAULT_DATA_DIR / "control_plane_fabric.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def rebuild(self, include_conversations: bool = True) -> dict[str, int]:
        entities = collect_knowledge_entities(self.factory_root)
        conversations: list[dict[str, Any]] = []
        if include_conversations:
            conversations.extend(_harvest_antigravity_sessions())
            conversations.extend(_harvest_copilot_sessions())

        with closing(self._connect()) as conn:
            conn.execute("DROP TABLE IF EXISTS fabric_items")
            conn.execute("DROP TABLE IF EXISTS fabric_fts")
            conn.execute(
                """
                CREATE TABLE fabric_items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    harness TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_date TEXT NOT NULL,
                    path TEXT NOT NULL,
                    abs_path TEXT NOT NULL,
                    upstream_json TEXT NOT NULL,
                    downstream_json TEXT NOT NULL,
                    mentioned_json TEXT NOT NULL,
                    body TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE fabric_fts USING fts5(
                    id,
                    title,
                    kind,
                    body,
                    mentioned_ids,
                    tokenize='porter unicode61'
                )
                """
            )

            all_rows = list(entities.values()) + conversations
            for item in all_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fabric_items
                    (id, title, kind, harness, status, created_date, path, abs_path,
                     upstream_json, downstream_json, mentioned_json, body)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["title"],
                        item["kind"],
                        item.get("harness", "factory"),
                        item.get("status", ""),
                        item.get("created_date", ""),
                        item.get("path", ""),
                        item.get("abs_path", ""),
                        json.dumps(item.get("upstream_refs", [])),
                        json.dumps(item.get("downstream_refs", [])),
                        json.dumps(item.get("mentioned_ids", [])),
                        item.get("body", ""),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO fabric_fts (id, title, kind, body, mentioned_ids)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["title"],
                        item["kind"],
                        item.get("body", ""),
                        " ".join(item.get("mentioned_ids", []) + item.get("upstream_refs", [])),
                    ),
                )
            conn.execute("CREATE TABLE IF NOT EXISTS fabric_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.executemany(
                "INSERT OR REPLACE INTO fabric_metadata VALUES (?, ?)",
                [("rebuilt_at", datetime.now(timezone.utc).isoformat()),
                 ("includes_conversations", json.dumps(include_conversations)),
                 ("factory_root", str(self.factory_root.resolve()))],
            )
            conn.commit()
        return {
            "knowledge_entities": len(entities),
            "conversations_indexed": len(conversations),
            "total_indexed": len(entities) + len(conversations),
        }

    def ensure_built(self) -> None:
        if not self.db_path.is_file():
            self.rebuild()
            return
        with closing(self._connect()) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fabric_items'"
            )
            if cur.fetchone() is None:
                self.rebuild()

    def freshness(self) -> dict[str, Any]:
        """Report cache age without building or reading personal conversations."""
        if not self.db_path.is_file():
            return {"built": False, "rebuilt_at": None, "includes_conversations": None, "factory_root": None}
        with closing(self._connect()) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            values = dict(conn.execute("SELECT key, value FROM fabric_metadata")) if "fabric_metadata" in tables else {}
        return {
            "built": "fabric_items" in tables,
            "rebuilt_at": values.get("rebuilt_at"),
            "includes_conversations": json.loads(values["includes_conversations"]) if "includes_conversations" in values else None,
            "factory_root": values.get("factory_root"),
        }

    def search(
        self, query: str = "", kind_filter: str = "", limit: int = 40, *, initialize: bool = True,
    ) -> dict[str, Any]:
        """Search across knowledge records and AI conversations with provenance chains."""
        if initialize:
            self.ensure_built()
        q = query.strip()
        with closing(self._connect()) as conn:
            counts_rows = conn.execute(
                "SELECT kind, COUNT(*) AS cnt FROM fabric_items GROUP BY kind ORDER BY cnt DESC"
            ).fetchall()
            counts = {r["kind"]: r["cnt"] for r in counts_rows}

            if not q:
                sql = "SELECT * FROM fabric_items"
                params: list[Any] = []
                if kind_filter:
                    sql += " WHERE kind = ?"
                    params.append(kind_filter)
                sql += " ORDER BY CASE WHEN kind='conversation' THEN 1 ELSE 0 END, id ASC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
                results = [self._format_row(r, snippet=r["body"][:260]) for r in rows]
                return {"query": q, "kind_filter": kind_filter, "counts": counts, "results": results}

            # Sanitize FTS5 query tokens
            tokens = re.findall(r"[A-Za-z0-9_-]+", q)
            fts_query = " OR ".join(f'"{t}"' for t in tokens if t)
            if not fts_query:
                return {"query": q, "kind_filter": kind_filter, "counts": counts, "results": []}

            sql = """
                SELECT f.*,
                       snippet(fabric_fts, 3, '<mark>', '</mark>', ' … ', 28) AS match_snippet,
                       bm25(fabric_fts, 5.0, 3.0, 1.0, 1.0, 2.0) AS rank_score
                FROM fabric_fts
                JOIN fabric_items f ON f.id = fabric_fts.id
                WHERE fabric_fts MATCH ?
            """
            params = [fts_query]
            if kind_filter:
                sql += " AND f.kind = ?"
                params.append(kind_filter)
            sql += " ORDER BY rank_score ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            results = [self._format_row(r, snippet=r["match_snippet"]) for r in rows]
            return {"query": q, "kind_filter": kind_filter, "counts": counts, "results": results}

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Return full entity details plus resolved upstream and downstream provenance nodes."""
        self.ensure_built()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM fabric_items WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                return None
            item = self._format_row(row, snippet=row["body"][:400], include_full_body=True)
            # Resolve upstream & downstream titles
            up_nodes = []
            for uid in item["upstream_refs"]:
                ur = conn.execute(
                    "SELECT id, title, kind, path FROM fabric_items WHERE id = ?", (uid,)
                ).fetchone()
                up_nodes.append(
                    dict(ur) if ur else {"id": uid, "title": uid, "kind": "external", "path": ""}
                )
            down_nodes = []
            for did in item["downstream_refs"]:
                dr = conn.execute(
                    "SELECT id, title, kind, path FROM fabric_items WHERE id = ?", (did,)
                ).fetchone()
                down_nodes.append(
                    dict(dr) if dr else {"id": did, "title": did, "kind": "external", "path": ""}
                )
            # Also find conversations that mention this entity ID
            conv_rows = conn.execute(
                "SELECT id, title, harness, created_date, path FROM fabric_items WHERE kind='conversation' AND mentioned_json LIKE ?",
                (f'%"{entity_id}"%',),
            ).fetchall()
            item["upstream_nodes"] = up_nodes
            item["downstream_nodes"] = down_nodes
            item["related_conversations"] = [dict(cr) for cr in conv_rows]
            return item

    @staticmethod
    def _format_row(
        row: sqlite3.Row, snippet: str = "", include_full_body: bool = False
    ) -> dict[str, Any]:
        out = {
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "harness": row["harness"],
            "status": row["status"],
            "created_date": row["created_date"],
            "path": row["path"],
            "abs_path": row["abs_path"],
            "upstream_refs": json.loads(row["upstream_json"]),
            "downstream_refs": json.loads(row["downstream_json"]),
            "mentioned_ids": json.loads(row["mentioned_json"]),
            "snippet": snippet,
        }
        if include_full_body:
            out["body"] = row["body"]
        return out
