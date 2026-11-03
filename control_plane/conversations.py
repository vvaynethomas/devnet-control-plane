"""Unified Cross-Platform Conversation Hub, Tokenomics & Handoff Engine (DEC-0004 / BL-0027).

Discovers and normalizes multi-turn conversations across:
1. Local Antigravity Sessions (~/.gemini/antigravity)
2. Local VS Code GitHub Copilot Chat (%APPDATA%/Code/User/workspaceStorage)
3. Local GitHub Copilot CLI (~/.copilot/session-state)
4. External / Cloud Imports (Microsoft Copilot, Remote GitHub Copilot Web, ChatGPT, Claude)

Provides granular 1-click copy controls, tokenomics analysis, and multi-dimensional filtering.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

from control_plane import FACTORY_ROOT, DEV_NETWORK_ROOT
from control_plane.fabric import redact_secrets, ID_RE
from control_plane.conversation_library import ConversationLibraryError, _configured_hub_api
from control_plane.conversation_hub_adapter import read_legacy_sessions, read_local_sessions


def estimate_tokens(text: str) -> int:
    """Heuristic token estimation (~4 chars per token for English/code)."""
    if not text:
        return 0
    return max(1, len(text.strip()) // 4)


def extract_code_blocks(text: str) -> list[str]:
    """Extract all fenced code blocks (```...```) from markdown text."""
    pattern = r"```(?:[a-zA-Z0-9_\-]+)?\n(.*?)```"
    matches = re.findall(pattern, text, flags=re.DOTALL)
    if not matches:
        # Fallback to backticks if any
        pattern_fallback = r"```(.*?)```"
        matches = re.findall(pattern_fallback, text, flags=re.DOTALL)
    return [m.strip() for m in matches if m.strip()]


class UnifiedConversationHub:
    """Aggregates local chat directories and user-imported cloud chats."""

    def __init__(self, data_dir: Path | None = None, factory_root: Path = FACTORY_ROOT) -> None:
        self.factory_root = factory_root
        self.data_dir = data_dir or (factory_root / "projects" / "agent-lifecycle-management" / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "conversations_hub.sqlite"
        self._hub_api = None
        self._hub_info: dict[str, str | None] | None = None
        self._source_diagnostics: list[str] = []
        self._init_db()

    def _get_hub_api(self):
        if self._hub_api is not None:
            return self._hub_api
        if self._hub_info is not None:
            return None
        try:
            self._hub_api, self._hub_info = _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code != "hub_unavailable":
                raise
            self._hub_info = {"implementation": "dncp-legacy-adapter", "version": None, "revision": None}
            self._source_diagnostics.append(
                "Optional Conversation Hub is not installed; using DNCP's legacy reader for existing conversation sources. "
                "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.4 producer adapters."
            )
        return self._hub_api

    def _read_local_sessions(
        self,
        source_kind: str,
        root: Path,
        max_sessions: int | None = None,
        *,
        selection_policy: str | None = None,
    ) -> list[dict[str, Any]] | None:
        if self._get_hub_api() is None:
            return None
        try:
            sessions, diagnostics, self._hub_info = read_local_sessions(
                source_kind, root,
                archive_key=f"dncp-local-{source_kind}",
                max_sessions=max_sessions,
                selection_policy=selection_policy,
            )
            self._source_diagnostics.extend(diagnostics)
            return sessions
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._source_diagnostics.append(
                f"{source_kind}: selected source could not be read by Conversation Hub ({type(exc).__name__})."
            )
            return []

    def _init_db(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS imported_chats (
                    session_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    model TEXT NOT NULL,
                    title TEXT NOT NULL,
                    workspace TEXT,
                    created_date TEXT,
                    raw_content TEXT NOT NULL,
                    turn_count INTEGER,
                    est_tokens INTEGER
                )
            """)
            conn.commit()

    def import_external_chat(
        self,
        title: str,
        platform: str,
        model: str,
        raw_text: str,
        workspace: str = "General",
    ) -> dict[str, Any]:
        """Onboard a chat from Microsoft Copilot, web export, Claude, or ChatGPT."""
        import uuid
        session_id = f"EXT-{uuid.uuid4().hex[:10]}"
        est_tok = estimate_tokens(raw_text)
        
        # Estimate turn count by counting user indicators or double linebreaks
        turns_approx = max(1, len(re.findall(r"(?:^|\n)(?:User|Prompt|Human|You):", raw_text, re.IGNORECASE)))
        created_at = datetime.now(timezone.utc).isoformat()[:19]

        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO imported_chats
                (session_id, platform, model, title, workspace, created_date, raw_content, turn_count, est_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                platform or "Microsoft Copilot (Imported)",
                model or "Copilot / GPT-4",
                title or "Imported Conversation",
                workspace,
                created_at,
                raw_text,
                turns_approx,
                est_tok,
            ))
            conn.commit()

        return {
            "session_id": session_id,
            "title": title,
            "platform": platform,
            "model": model,
            "est_tokens": est_tok,
            "created_date": created_at,
        }

    def scan_antigravity(self, brain_root: Path | None = None) -> list[dict[str, Any]]:
        """Harvest local Antigravity sessions."""
        brain_root = brain_root or (Path(os.path.expanduser("~")) / ".gemini" / "antigravity" / "brain")
        selected = self._read_local_sessions(
            "antigravity",
            brain_root,
            max_sessions=25,
            selection_policy="directory-first",
        )
        if selected is not None:
            sessions = [session for session in selected if session["turns"]]
            for session in sessions:
                session["workspace"] = self.factory_root.name
            return sessions
        sessions = []
        if not brain_root.is_dir():
            return sessions

        subdirs = sorted([d for d in brain_root.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
        for sdir in subdirs[:25]:
            t_path = sdir / ".system_generated" / "logs" / "transcript.jsonl"
            if not t_path.is_file():
                continue
            turns = []
            current_turn: dict[str, Any] | None = None
            first_time = ""
            try:
                with open(t_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        tp = obj.get("type")
                        if tp == "USER_INPUT":
                            if current_turn:
                                turns.append(current_turn)
                            content = re.sub(r"</?USER_REQUEST>", "", str(obj.get("content") or "")).strip()
                            clean = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", content, flags=re.DOTALL)
                            clean = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", clean, flags=re.DOTALL).strip()
                            if not first_time and obj.get("created_at"):
                                first_time = str(obj["created_at"])[:19]
                            current_turn = {
                                "turn_index": len(turns) + 1,
                                "timestamp": obj.get("created_at", "")[:19],
                                "user_prompt": redact_secrets(clean),
                                "assistant_responses": [],
                                "tool_calls": [],
                            }
                        elif tp == "PLANNER_RESPONSE" and current_turn:
                            resp = str(obj.get("content") or "").strip()
                            if resp:
                                current_turn["assistant_responses"].append(redact_secrets(resp))
                            for tc in obj.get("tool_calls", []):
                                fn = tc.get("function", {}).get("name") if isinstance(tc, dict) else str(tc)
                                if fn:
                                    current_turn["tool_calls"].append(fn)
                if current_turn:
                    turns.append(current_turn)
            except Exception:
                continue

            if turns:
                total_in = sum(estimate_tokens(t["user_prompt"]) for t in turns)
                total_out = sum(estimate_tokens(" ".join(t["assistant_responses"])) for t in turns)
                title = turns[0]["user_prompt"].replace("\n", " ")[:90] if turns else f"Session {sdir.name[:8]}"
                sessions.append({
                    "session_id": f"AGY-{sdir.name[:12]}",
                    "full_session_id": sdir.name,
                    "platform": "Antigravity",
                    "model": "Gemini 3.8 Flash",
                    "title": title,
                    "workspace": self.factory_root.name,
                    "created_date": first_time or datetime.fromtimestamp(t_path.stat().st_mtime, tz=timezone.utc).isoformat()[:19],
                    "turns": turns,
                    "turn_count": len(turns),
                    "est_input_tokens": total_in,
                    "est_output_tokens": total_out,
                    "est_total_tokens": total_in + total_out,
                    "source_path": str(t_path.resolve()),
                })
        return sessions

    def scan_vscode_copilot(self, workspace_storage_root: Path | None = None) -> list[dict[str, Any]]:
        """Harvest local VS Code GitHub Copilot Chat sessions."""
        if workspace_storage_root is None:
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return []
            workspace_storage_root = Path(appdata) / "Code" / "User" / "workspaceStorage"
        selected = self._read_local_sessions("vscode-copilot", workspace_storage_root, max_sessions=500)
        if selected is not None:
            return selected
        if not workspace_storage_root:
            return []
        ws_storage = workspace_storage_root
        if not ws_storage.is_dir():
            return []

        sessions = []
        for chat_dir in ws_storage.glob("*/chatSessions"):
            for f in chat_dir.glob("*.jsonl"):
                try:
                    creation_time = ""
                    model_name = "GitHub Copilot"
                    user_prompts = []
                    assistant_replies = []
                    with open(f, "r", encoding="utf-8", errors="replace") as jf:
                        for line in jf:
                            if not line.strip():
                                continue
                            obj = json.loads(line)
                            val = obj.get("v")
                            if isinstance(val, dict):
                                if not creation_time and val.get("creationDate"):
                                    creation_time = datetime.fromtimestamp(val["creationDate"] / 1000.0, tz=timezone.utc).isoformat()[:19]
                                sel = val.get("inputState", {}).get("selectedModel", {})
                                if isinstance(sel, dict):
                                    m_meta = sel.get("metadata", {})
                                    model_name = m_meta.get("name") or m_meta.get("id") or model_name
                                inp = val.get("inputText", "").strip()
                                if inp and inp not in user_prompts:
                                    user_prompts.append(inp)
                            elif isinstance(val, str) and len(val.strip()) > 20:
                                assistant_replies.append(val.strip())

                    if user_prompts:
                        turns = []
                        for i, p in enumerate(user_prompts):
                            ans = assistant_replies[i] if i < len(assistant_replies) else "Response in VS Code session"
                            turns.append({
                                "turn_index": i + 1,
                                "timestamp": creation_time,
                                "user_prompt": redact_secrets(p),
                                "assistant_responses": [redact_secrets(ans)],
                                "tool_calls": [],
                            })
                        tot_in = sum(estimate_tokens(t["user_prompt"]) for t in turns)
                        tot_out = sum(estimate_tokens(" ".join(t["assistant_responses"])) for t in turns)
                        sessions.append({
                            "session_id": f"VSC-{f.stem[:12]}",
                            "full_session_id": f.stem,
                            "platform": "VS Code GitHub Copilot",
                            "model": model_name,
                            "title": user_prompts[0].replace("\n", " ")[:90],
                            "workspace": "VS Code Workspace",
                            "created_date": creation_time or "",
                            "turns": turns,
                            "turn_count": len(turns),
                            "est_input_tokens": tot_in,
                            "est_output_tokens": tot_out,
                            "est_total_tokens": tot_in + tot_out,
                            "source_path": str(f.resolve()),
                        })
                except Exception:
                    continue
        return sessions

    def scan_copilot_cli(self, session_state_root: Path | None = None) -> list[dict[str, Any]]:
        """Harvest local GitHub Copilot CLI event streams."""
        root = session_state_root or (Path(os.path.expanduser("~")) / ".copilot" / "session-state")
        selected = self._read_local_sessions("copilot-cli", root, max_sessions=500)
        if selected is not None:
            return selected
        if not root.is_dir():
            return []
        sessions = []
        for f in root.glob("*/events.jsonl"):
            try:
                snippets = []
                created_date = ""
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh.readlines()[:100]:
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        if not created_date and obj.get("timestamp"):
                            created_date = str(obj["timestamp"])[:19]
                        msg = obj.get("message") or obj.get("content") or ""
                        if isinstance(msg, str) and len(msg.strip()) > 15:
                            snippets.append(msg.strip())
                if snippets:
                    turns = [{
                        "turn_index": i + 1,
                        "timestamp": created_date,
                        "user_prompt": redact_secrets(s),
                        "assistant_responses": ["Command event stream execution"],
                        "tool_calls": [],
                    } for i, s in enumerate(snippets[:10])]
                    tot = sum(estimate_tokens(s) for s in snippets)
                    sessions.append({
                        "session_id": f"CLI-{f.parent.name[:12]}",
                        "full_session_id": f.parent.name,
                        "platform": "GitHub Copilot CLI",
                        "model": "Copilot CLI",
                        "title": snippets[0].replace("\n", " ")[:90],
                        "workspace": "Terminal",
                        "created_date": created_date,
                        "turns": turns,
                        "turn_count": len(turns),
                        "est_input_tokens": tot // 2,
                        "est_output_tokens": tot // 2,
                        "est_total_tokens": tot,
                        "source_path": str(f.resolve()),
                    })
            except Exception:
                continue
        return sessions

    def get_imported_chats(self) -> list[dict[str, Any]]:
        """Retrieve user-imported cloud chats (Microsoft Copilot, ChatGPT, Claude)."""
        if self._get_hub_api() is not None:
            try:
                sessions, diagnostics, self._hub_info = read_legacy_sessions(
                    self.db_path, archive_key="dncp-imported-chats",
                )
                self._source_diagnostics.extend(diagnostics)
                return sessions
            except ValueError as exc:
                if "contains no imported_chats rows" in str(exc):
                    return []
                self._source_diagnostics.append(
                    f"legacy-imported-chats: selected database could not be read by Conversation Hub ({type(exc).__name__})."
                )
                return []
        sessions = []
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT session_id, platform, model, title, workspace, created_date, raw_content, turn_count, est_tokens
                FROM imported_chats
                ORDER BY created_date DESC
            """)
            for row in cur.fetchall():
                sid, plat, mod, title, ws, dt, content, tc, est_t = row
                # Split raw content into readable turns
                paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
                turns = []
                for idx, p in enumerate(paragraphs[:20]):
                    turns.append({
                        "turn_index": idx + 1,
                        "timestamp": dt,
                        "user_prompt": p if idx % 2 == 0 else f"Turn {idx+1}",
                        "assistant_responses": [p] if idx % 2 != 0 else [],
                        "tool_calls": [],
                    })
                sessions.append({
                    "session_id": sid,
                    "full_session_id": sid,
                    "platform": plat,
                    "model": mod,
                    "title": title,
                    "workspace": ws,
                    "created_date": dt,
                    "turns": turns,
                    "turn_count": tc or len(turns),
                    "est_input_tokens": est_t // 2,
                    "est_output_tokens": est_t // 2,
                    "est_total_tokens": est_t,
                    "source_path": f"database://{sid}",
                })
        return sessions

    def get_all_conversations(
        self,
        query: str = "",
        platform_filter: str = "",
        model_filter: str = "",
    ) -> dict[str, Any]:
        """Aggregate, search, and calculate tokenomics across all sources."""
        self._source_diagnostics = []
        if self._get_hub_api() is None and not self._source_diagnostics:
            self._source_diagnostics.append(
                "Optional Conversation Hub is not installed; using DNCP's legacy reader for existing conversation sources. "
                "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.4 producer adapters."
            )
        all_sessions = (
            self.scan_antigravity() +
            self.scan_vscode_copilot() +
            self.scan_copilot_cli() +
            self.get_imported_chats()
        )

        # Sort by creation date descending
        all_sessions.sort(key=lambda s: s.get("created_date", ""), reverse=True)

        # Apply filters
        filtered = []
        q_lower = query.lower().strip()
        for s in all_sessions:
            if platform_filter and s["platform"].lower() != platform_filter.lower():
                continue
            if model_filter and s["model"].lower() != model_filter.lower():
                continue
            if q_lower:
                text_to_search = (s["title"] + " " + s["model"] + " " + s["workspace"] + " " +
                                  " ".join(t["user_prompt"] + " " + " ".join(t["assistant_responses"]) for t in s.get("turns", []))).lower()
                if q_lower not in text_to_search:
                    continue
            filtered.append(s)

        # Compute tokenomics & model analytics
        total_tokens = sum(s.get("est_total_tokens", 0) for s in all_sessions)
        total_in = sum(s.get("est_input_tokens", 0) for s in all_sessions)
        total_out = sum(s.get("est_output_tokens", 0) for s in all_sessions)
        total_turns = sum(s.get("turn_count", 0) for s in all_sessions)

        platforms_count: dict[str, int] = {}
        models_count: dict[str, int] = {}
        for s in all_sessions:
            p = s["platform"]
            platforms_count[p] = platforms_count.get(p, 0) + 1
            m = s["model"]
            models_count[m] = models_count.get(m, 0) + 1

        return {
            "summary": {
                "total_sessions": len(all_sessions),
                "filtered_sessions": len(filtered),
                "total_turns": total_turns,
                "est_total_tokens": total_tokens,
                "est_input_tokens": total_in,
                "est_output_tokens": total_out,
                "platforms": platforms_count,
                "models": models_count,
            },
            "source_adapter": {
                **(self._hub_info or {
                    "implementation": "dncp-legacy-adapter",
                    "version": None,
                    "revision": None,
                }),
                "diagnostics": self._source_diagnostics,
            },
            "sessions": filtered,
        }
