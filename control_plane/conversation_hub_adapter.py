"""Compatibility projections from the optional Conversation Hub model to DNCP UI records."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .conversation_library import ConversationHubAPI, _configured_hub_api


_SOURCE_READERS = {
    "antigravity": ("read_antigravity_sessions", 25, "AGY-", "Antigravity", "Gemini 3.8 Flash"),
    "vscode-copilot": ("read_vscode_copilot_sessions", 500, "VSC-", "VS Code GitHub Copilot", "GitHub Copilot"),
    "copilot-cli": ("read_copilot_cli_sessions", 500, "CLI-", "GitHub Copilot CLI", "Copilot CLI"),
}


def local_source_path(uri: str) -> Path:
    """Convert a selected local file URI, including Windows UNC paths, to a filesystem path."""
    parsed = urlsplit(uri)
    if parsed.scheme != "file":
        raise ValueError("Conversation Hub returned a non-local source URI for a local file")
    if parsed.netloc not in {"", "localhost"}:
        if (
            os.name != "nt"
            or parsed.username
            or parsed.password
            or parsed.port
            or not re.fullmatch(r"[A-Za-z0-9._-]+", parsed.netloc)
        ):
            raise ValueError("Conversation Hub returned a non-local source URI for a local file")
        return Path(f"\\\\{parsed.netloc}{url2pathname(parsed.path)}")
    return Path(url2pathname(parsed.path))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text.strip()) // 4)


def _session_from_conversation(
    conversation: Any,
    api: ConversationHubAPI,
    source_kind: str,
    *,
    max_messages: int | None = None,
) -> dict[str, Any]:
    view = api.conversation_view(conversation)
    metadata = view.metadata
    source_id = conversation.source.session_id
    source_record = conversation.source_record
    unassigned_messages: list[dict[str, str]] = []
    unclassified_tokens = 0
    messages = view.messages
    if source_kind == "copilot-cli" and max_messages is not None:
        messages = tuple(message for message in messages if len(message.content.strip()) > 15)[:max_messages]
    selected_ids = {message.id for message in messages}

    def selected(items: Any) -> list[Any]:
        return [message for message in items if message.id in selected_ids]

    def content(message: Any) -> str:
        return message.content.strip() if source_kind == "copilot-cli" else message.content

    if source_kind == "legacy":
        session_id = source_id
        platform = conversation.source.platform
        model = metadata.model or "Copilot / GPT-4"
        workspace = metadata.workspace or "General"
        title = metadata.title or "Imported Conversation"
        paragraphs = view.legacy_display.paragraphs if view.legacy_display else ()
        turns = [{
            "turn_index": paragraph.index,
            "timestamp": metadata.created_at or "",
            "user_prompt": paragraph.content if paragraph.role_hint == "user-display-hint" else f"Turn {paragraph.index}",
            "assistant_responses": [paragraph.content] if paragraph.role_hint == "assistant-display-hint" else [],
            "tool_calls": [],
        } for paragraph in paragraphs]
        estimated = metadata.legacy_estimated_tokens or 0
        turn_count = metadata.legacy_turn_count or len(turns)
        input_tokens = estimated // 2
        output_tokens = estimated // 2
        source_path = f"database://{source_id}"
    else:
        _, _, prefix, platform, fallback_model = _SOURCE_READERS[source_kind]
        turns = []
        for turn in view.turns:
            if not selected(turn.messages):
                continue
            turns.append({
                "turn_index": turn.index,
                "timestamp": turn.timestamp or "",
                "user_message_count": len(selected(turn.user_messages)),
                "user_prompt": "\n\n".join(content(message) for message in selected(turn.user_messages)),
                "assistant_responses": [content(message) for message in selected(turn.assistant_messages)],
                "other_messages": [
                    {
                        "role": message.role,
                        "source_role": message.source_role,
                        "content": content(message),
                    }
                    for message in selected(turn.other_messages)
                ],
                "tool_calls": list(turn.tool_calls),
                "messages": [
                    {"role": message.role, "source_role": message.source_role, "content": content(message)}
                    for message in selected(turn.messages)
                ],
            })
        unassigned_messages = [
            {
                "role": message.role,
                "source_role": message.source_role,
                "content": content(message),
            }
            for message in selected(view.unassigned_messages)
        ]
        title = metadata.title or next(
            (turn["user_prompt"].replace("\n", " ")[:90] for turn in turns if turn["user_prompt"]),
            next(
                (content(message).replace("\n", " ")[:90]
                 for message in messages if len(message.content.strip()) > 15),
                f"Session {source_id[:8]}",
            ) if source_kind == "copilot-cli" else f"Session {source_id[:8]}",
        )
        model = metadata.model or fallback_model
        workspace = metadata.workspace or (
            "VS Code Workspace" if source_kind == "vscode-copilot" else
            "Terminal" if source_kind == "copilot-cli" else "General"
        )
        session_id = f"{prefix}{source_id[:12]}"
        input_tokens = sum(estimate_tokens(turn["user_prompt"]) for turn in turns)
        output_tokens = sum(
            estimate_tokens(text) for turn in turns for text in turn["assistant_responses"]
        )
        input_tokens += sum(
            estimate_tokens(message.content)
            for message in selected(view.unassigned_messages) if message.role == "user"
        )
        output_tokens += sum(
            estimate_tokens(message.content)
            for message in selected(view.unassigned_messages) if message.role == "assistant"
        )
        unclassified_tokens = sum(
            estimate_tokens(message.content)
            for message in messages if message.role not in {"user", "assistant"}
        )
        turn_count = len(turns)
        source_uri = source_record.get("source_path") or conversation.provenance.export_uri
        if not isinstance(source_uri, str):
            source_uri = conversation.provenance.export_uri
        source_path = str(local_source_path(source_uri))

    return {
        "session_id": session_id,
        "full_session_id": source_id,
        "platform": platform,
        "model": model,
        "title": title,
        "workspace": workspace,
        "created_date": metadata.created_at or "",
        "turns": turns,
        "unassigned_messages": unassigned_messages,
        "turn_count": turn_count,
        "est_input_tokens": input_tokens,
        "est_output_tokens": output_tokens,
        "est_total_tokens": (
            estimated if source_kind == "legacy"
            else input_tokens + output_tokens + unclassified_tokens
        ),
        "source_path": source_path,
        **({
            "source_uri": source_uri,
            "est_unclassified_tokens": unclassified_tokens,
            "messages": [
                {"role": message.role, "source_role": message.source_role, "content": content(message)}
                for message in messages
            ],
        } if source_kind != "legacy" else {}),
    }


def read_local_sessions(
    source_kind: str,
    root: Path,
    *,
    archive_key: str,
    max_sessions: int | None = None,
    selection_policy: str | None = None,
    max_messages: int | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str | None]]:
    api, info = _configured_hub_api()
    reader_name, default_limit, _, _, _ = _SOURCE_READERS[source_kind]
    reader = getattr(api, reader_name)
    limit = default_limit if max_sessions is None else max_sessions
    if not root.is_dir():
        return [], [], info
    options: dict[str, Any] = {
        "archive_key": archive_key, "max_sessions": limit, "malformed_sources": "skip-file",
    }
    if source_kind == "antigravity" and selection_policy is not None:
        options["selection_policy"] = selection_policy
    result = reader(root, **options)
    conversations = [conversation for batch in result.batches for conversation in batch.conversations]
    sessions = [
        _session_from_conversation(conversation, api, source_kind, max_messages=max_messages)
        for conversation in conversations
    ]
    if source_kind == "copilot-cli" and max_messages is not None:
        sessions = [session for session in sessions if session["messages"]]
    diagnostics = list(result.limitations)
    if max_messages is not None and source_kind == "copilot-cli":
        diagnostics.append(
            f"copilot-cli: display limited to the first {max_messages} qualifying messages per selected source; "
            "later messages excluded from presentation and search."
        )
    diagnostics.extend(result.skipped_inputs)
    if result.skipped_count:
        diagnostics.append(
            f"{source_kind}: {result.skipped_count} malformed selected source files skipped "
            f"within {result.selected_count} selected slots; no cap refill."
        )
    if result.omitted_count:
        diagnostics.append(
            f"{source_kind}: {result.omitted_count} additional source files were omitted by the producer limit."
        )
    return sessions, list(dict.fromkeys(diagnostics)), info


def read_antigravity_transcript(
    transcript_path: Path, *, archive_key: str, session_id: str,
) -> tuple[dict[str, Any], list[str]]:
    api, _ = _configured_hub_api()
    batch = api.read_antigravity_transcript(
        transcript_path, archive_key=archive_key, session_id=session_id,
        malformed_lines="skip-line",
    )
    conversation = batch.conversations[0]
    return _session_from_conversation(conversation, api, "antigravity"), list(conversation.limitations)


def read_legacy_sessions(
    database_path: Path,
    *,
    archive_key: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, str | None]]:
    api, info = _configured_hub_api()
    batch = api.read_legacy_imported_chats(database_path, archive_key=archive_key)
    sessions = [
        _session_from_conversation(conversation, api, "legacy")
        for conversation in batch.conversations
    ]
    diagnostics = list(dict.fromkeys(
        limitation
        for conversation in batch.conversations
        for limitation in conversation.limitations
    ))
    return sessions, diagnostics, info
