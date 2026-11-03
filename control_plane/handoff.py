"""Cross-Session Conversation Handoff & Interaction Sync Engine (DEC-0004 / BL-0027).

Parses multi-turn transcripts across Antigravity, Copilot CLI, and local AI sessions,
tracks 'who said what and where we are', and compiles 1-click Context Handoff Packets
to eliminate manual turn-by-turn copy-pasting across AI interfaces.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from control_plane import FACTORY_ROOT, DEV_NETWORK_ROOT
from control_plane.fabric import redact_secrets, ID_RE
from control_plane.conversation_library import ConversationLibraryError, _configured_hub_api
from control_plane.conversation_hub_adapter import (
    local_source_path, read_antigravity_transcript, read_local_sessions,
)

logger = logging.getLogger(__name__)


def _get_git_state(repo_dir: Path) -> dict[str, str]:
    """Retrieve current branch, head commit, and dirty status."""
    branch = "unknown"
    commit = "unknown"
    status_summary = "clean"
    try:
        b_res = subprocess.run(["git", "branch", "--show-current"], cwd=repo_dir, capture_output=True, text=True)
        if b_res.returncode == 0 and b_res.stdout.strip():
            branch = b_res.stdout.strip()
        c_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
        if c_res.returncode == 0:
            commit = c_res.stdout.strip()
        s_res = subprocess.run(["git", "status", "--short"], cwd=repo_dir, capture_output=True, text=True)
        if s_res.returncode == 0 and s_res.stdout.strip():
            status_summary = f"dirty ({len(s_res.stdout.strip().splitlines())} modified files)"
    except Exception:
        pass
    return {"branch": branch, "commit": commit, "status": status_summary}


def discover_antigravity_sessions(max_sessions: int = 20) -> list[dict[str, Any]]:
    """Scan local Antigravity brain transcripts."""
    brain_root = Path(os.path.expanduser("~")) / ".gemini" / "antigravity" / "brain"
    sessions: list[dict[str, Any]] = []
    if not brain_root.is_dir():
        return sessions
    try:
        adapted, diagnostics, _ = read_local_sessions(
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
            "Optional Conversation Hub is not installed; handoff uses its legacy Antigravity reader. "
            "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.5 adapter."
        )
        adapted = None
        diagnostics = []
    except (ValueError, OSError) as exc:
        logger.warning("Conversation Hub could not read the selected Antigravity source (%s).", type(exc).__name__)
        return sessions
    if adapted is not None:
        for item in diagnostics:
            logger.warning("Antigravity handoff source adapter: %s", item)
        for session in adapted:
            turns = session["turns"]
            user_turns = [
                turn for turn in turns
                if turn.get("user_message_count", bool(turn["user_prompt"]))
            ]
            if not user_turns:
                continue
            last_turn_time = user_turns[-1]["timestamp"]
            source_path = local_source_path(session["source_uri"])
            last_turn_time = last_turn_time[:19] if last_turn_time else ""
            sessions.append({
                "session_id": session["full_session_id"],
                "harness": "antigravity",
                "title": user_turns[0]["user_prompt"].replace("\n", " ")[:110]
                or f"Session {session['full_session_id'][:8]}",
                "user_turns": len(user_turns),
                "last_modified": last_turn_time or (
                    datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc).isoformat()[:19]
                ),
                "transcript_path": str(source_path),
                "turns": turns,
            })
        return sessions

    subdirs = sorted(
        [d for d in brain_root.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    for sdir in subdirs[:max_sessions]:
        t_path = sdir / ".system_generated" / "logs" / "transcript.jsonl"
        if not t_path.is_file():
            continue
        first_prompt = ""
        user_turn_count = 0
        last_turn_time = ""
        try:
            with open(t_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if obj.get("type") == "USER_INPUT":
                        user_turn_count += 1
                        last_turn_time = obj.get("created_at", "")[:19]
                        if not first_prompt:
                            c = str(obj.get("content") or "")
                            clean = re.sub(r"</?USER_REQUEST>", "", c).strip()
                            first_prompt = clean.replace("\n", " ")[:110]
        except Exception:
            continue

        if user_turn_count > 0:
            sessions.append({
                "session_id": sdir.name,
                "harness": "antigravity",
                "title": first_prompt or f"Session {sdir.name[:8]}",
                "user_turns": user_turn_count,
                "last_modified": last_turn_time or datetime.fromtimestamp(t_path.stat().st_mtime, tz=timezone.utc).isoformat()[:19],
                "transcript_path": str(t_path.resolve()),
            })

    return sessions


def parse_session_turns(transcript_path: Path) -> list[dict[str, Any]]:
    """Parse a transcript.jsonl into structured dialogue turns (user request -> model replies + tools)."""
    turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None

    if not transcript_path.is_file():
        return turns
    try:
        _configured_hub_api()
        selected_path = transcript_path.resolve(strict=True)
        standard_layout = (
            selected_path.name == "transcript.jsonl"
            and selected_path.parent.name == "logs"
            and selected_path.parent.parent.name == ".system_generated"
        )
        selected, diagnostics = read_antigravity_transcript(
            selected_path,
            archive_key="dncp-local-antigravity",
            session_id=(
                selected_path.parents[2].name if standard_layout
                else hashlib.sha256(selected_path.as_uri().encode("utf-8")).hexdigest()
            ),
        )
    except ConversationLibraryError as exc:
        if exc.code != "hub_unavailable":
            raise
        logger.warning(
            "Optional Conversation Hub is not installed; handoff uses its legacy Antigravity parser. "
            "Install devnet-control-plane[conversation-hub] to use the pinned v0.1.5 adapter."
        )
        selected = None
        diagnostics = []
    except (OSError, ValueError) as exc:
        logger.warning("Conversation Hub could not read the selected Antigravity transcript (%s).", type(exc).__name__)
        return turns
    if selected is not None:
        for item in diagnostics:
            logger.warning("Antigravity handoff source adapter: %s", item)
        return selected["turns"]

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            tp = obj.get("type")
            if tp == "USER_INPUT":
                if current_turn:
                    turns.append(current_turn)
                content = str(obj.get("content") or "")
                clean = re.sub(r"</?USER_REQUEST>", "", content).strip()
                # Remove XML metadata and harness settings noise if present
                clean = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", clean, flags=re.DOTALL)
                clean = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", clean, flags=re.DOTALL).strip()
                current_turn = {
                    "turn_index": len(turns) + 1,
                    "timestamp": obj.get("created_at", "")[:19],
                    "user_prompt": redact_secrets(clean),
                    "assistant_responses": [],
                    "tool_calls": [],
                }
            elif tp == "PLANNER_RESPONSE" and current_turn:
                resp_text = str(obj.get("content") or "").strip()
                if resp_text:
                    current_turn["assistant_responses"].append(redact_secrets(resp_text))
                for tc in obj.get("tool_calls", []):
                    fn_name = ""
                    if isinstance(tc, dict):
                        fn_name = tc.get("function", {}).get("name") or tc.get("name") or ""
                        args = tc.get("function", {}).get("arguments") or tc.get("args") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        summary = tc.get("toolSummary") or (args.get("toolSummary") if isinstance(args, dict) else "")
                        label = f"{fn_name}: {summary}" if summary else fn_name
                    elif isinstance(tc, str):
                        label = tc
                    if label:
                        current_turn["tool_calls"].append(label)

    if current_turn:
        turns.append(current_turn)

    return turns


def compile_context_handoff(
    session_id: str | None = None,
    turns_limit: int | None = None,
    factory_root: Path = FACTORY_ROOT,
    network_root: Path = DEV_NETWORK_ROOT,
) -> dict[str, Any]:
    """Compile a complete, self-contained Context Handoff Packet ready to paste into any AI chat."""
    sessions = discover_antigravity_sessions()
    target_session = None

    if session_id:
        for s in sessions:
            if s["session_id"].startswith(session_id):
                target_session = s
                break
    elif sessions:
        target_session = sessions[0]

    if not target_session:
        # Fallback to current conversation if known
        return {
            "error": "No matching conversation transcript found.",
            "available_sessions": [s["session_id"] for s in sessions[:5]],
        }

    t_path = Path(target_session["transcript_path"])
    all_turns = target_session.get("turns")
    if all_turns is None:
        all_turns = parse_session_turns(t_path)
    selected_turns = all_turns[-turns_limit:] if turns_limit else all_turns

    git_info = _get_git_state(factory_root)

    # Extract all factory entity IDs mentioned across the conversation
    all_text = " ".join([t["user_prompt"] + " " + " ".join(t["assistant_responses"]) for t in selected_turns])
    mentioned_ids = sorted(set(m.group(0) for m in ID_RE.finditer(all_text)))

    # Construct the Markdown Handoff Document
    lines = [
        "# == AI CONVERSATION CONTEXT HANDOFF ==",
        f"> **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | **Harness:** {target_session['harness']} | **Session:** `{target_session['session_id'][:12]}`",
        f"> **Workspace:** `{factory_root.name}` | **Git:** `{git_info['branch']}` @ `{git_info['commit']}` ({git_info['status']})",
        "",
        "## 1. Executive Context & Current State ('Where We Are')",
        f"- **Primary Focus:** {target_session['title']}",
        f"- **Active Conversation Turns:** {len(all_turns)} total turns ({len(selected_turns)} included in this handoff)",
        f"- **Entities & ADRs Referenced:** {', '.join(f'`{eid}`' for eid in mentioned_ids) if mentioned_ids else 'None recorded'}",
        "",
        "## 2. Conversation Dialogue Timeline ('Who Said What')",
    ]

    for turn in selected_turns:
        idx = turn["turn_index"]
        ts = turn["timestamp"] or "Time --"
        lines.append(f"### Turn {idx} - [USER] ({ts})")
        lines.append(f"> {turn['user_prompt'].replace(chr(10), chr(10) + '> ')}")
        lines.append("")

        if turn["tool_calls"]:
            tools_summary = ", ".join(f"`{tc}`" for tc in turn["tool_calls"][:6])
            if len(turn["tool_calls"]) > 6:
                tools_summary += f" *(+{len(turn['tool_calls'])-6} more)*"
            lines.append(f"*Tools executed:* {tools_summary}\n")

        if turn["assistant_responses"]:
            lines.append(f"### Turn {idx} - [ASSISTANT]")
            resp_body = "\n\n".join(turn["assistant_responses"])
            lines.append(resp_body)
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 3. Instructions for Successor Agent")
    lines.append("You are continuing work from the preceding session. Review the dialogue timeline and entity refs above. Continue from where we left off without re-asking questions already answered or rebuilding components already completed.")

    markdown_handoff = "\n".join(lines)

    return {
        "session_id": target_session["session_id"],
        "title": target_session["title"],
        "total_turns": len(all_turns),
        "included_turns": len(selected_turns),
        "git_state": git_info,
        "mentioned_entities": mentioned_ids,
        "markdown": markdown_handoff,
    }


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard across Windows, macOS, and Linux without external pip dependencies."""
    try:
        if sys.platform == "win32":
            # Use clip.exe on Windows
            p = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-16le"))
            return p.returncode == 0
        elif sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        else:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
    except Exception:
        return False
