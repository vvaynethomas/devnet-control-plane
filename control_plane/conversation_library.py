"""Explicit, read-only consumer of the pinned PRJ-0006 version-1 library."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, NoReturn


PRODUCER_REVISION = "2673a87a2bef8c6055ed63ee5200aa1cde96ab37"
APPLICATION_ID = 0x41434831
SCHEMA_VERSION = 1
MAX_LIBRARY_BYTES = 32 * 1024 * 1024
MAX_OBSERVATIONS = 256
MAX_RECORD_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")


class ConversationLibraryError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _incompatible() -> NoReturn:
    raise ConversationLibraryError(
        "schema_incompatible", "Library does not match the pinned PRJ-0006 version-1 contract.",
    )


def _texts(record: dict[str, Any], names: tuple[str, ...], nullable: bool = False) -> None:
    for name in names:
        if name not in record or not (
            isinstance(record[name], str) or (nullable and record[name] is None)
        ):
            _incompatible()


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _incompatible()
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    _incompatible()


def _validate_record(raw: str, key: tuple[str, str, str, str]) -> dict[str, Any]:
    record = json.loads(raw, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int:
        _incompatible()
    if record["schema_version"] != SCHEMA_VERSION:
        _incompatible()
    _texts(record, ("id", "revision"))
    _texts(record, ("created_at", "updated_at", "source_current_node_id"), nullable=True)
    if not all(SHA256.fullmatch(record[name]) for name in ("id", "revision")):
        _incompatible()
    source, provenance = record.get("source"), record.get("provenance")
    if not isinstance(source, dict) or not isinstance(provenance, dict):
        _incompatible()
    _texts(source, ("archive_key", "platform", "edition", "session_id"))
    _texts(source, ("source_id", "source_name", "native_session_id"), nullable=True)
    _texts(provenance, ("producer", "declared_version", "export_uri", "export_sha256", "pointer"))
    if not SHA256.fullmatch(provenance["export_sha256"]):
        _incompatible()
    if (record["id"], record["revision"], provenance["export_sha256"], provenance["export_uri"]) != key:
        _incompatible()
    messages = record.get("messages")
    limitations = record.get("limitations")
    if not isinstance(record.get("source_record"), dict) or not isinstance(messages, list):
        _incompatible()
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        _incompatible()
    previous_position = -1
    for message in messages:
        if not isinstance(message, dict):
            _incompatible()
        _texts(message, ("id", "role", "source_role", "content", "pointer"))
        _texts(message, ("timestamp", "source_event_id", "parent_source_event_id"), nullable=True)
        children = message.get("child_source_event_ids")
        if not isinstance(children, list) or not all(isinstance(child, str) for child in children):
            _incompatible()
        if type(message.get("position")) is not int or message["position"] <= previous_position:
            _incompatible()
        previous_position = message["position"]
        if message["role"] not in {"user", "assistant", "system", "tool", "unknown"}:
            _incompatible()
        if not SHA256.fullmatch(message["id"]):
            _incompatible()
    return record


def _file_state(path: Path) -> tuple[int, int, int, int, int]:
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise ConversationLibraryError(
                "library_busy", "Close the producer and checkpoint its library before reading; sidecar present.",
            )
    stat = path.stat()
    if not path.is_file():
        raise ConversationLibraryError("unavailable", "Selected conversation library is not a file.", 503)
    if stat.st_size > MAX_LIBRARY_BYTES:
        raise ConversationLibraryError("limit_exceeded", "Library exceeds the 32 MiB consumer limit.", 413)
    with path.open("rb") as source:
        header = source.read(20)
    if header[18:20] == b"\x02\x02":
        raise ConversationLibraryError(
            "library_busy", "WAL libraries are unsupported; close and checkpoint with the producer first.",
        )
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_conversation_library(
    library: Path, expected_snapshot: str | None = None,
) -> dict[str, Any]:
    """Read all bounded observations, never select a current revision or follow a URI."""
    if expected_snapshot is not None and not SHA256.fullmatch(expected_snapshot):
        raise ConversationLibraryError("invalid_request", "Expected snapshot must be a lowercase SHA-256.", 400)
    try:
        path = library.resolve(strict=True)
        before = _file_state(path)
        # Immutable mode prevents SQLite from creating sidecars. Only a quiescent,
        # rollback-journal library is supported; WAL and changes are refused.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.set_progress_handler(lambda: 1, 1_000_000)
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                _incompatible()
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                _incompatible()
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ConversationLibraryError(
                    "library_busy", "Only a closed rollback-journal library is supported.",
                )
            for table, columns in {
                "exports": ["sha256", "raw"],
                "revisions": ["conversation_id", "revision"],
                "observations": ["conversation_id", "revision", "export_sha256", "export_uri", "normalized_json"],
            }.items():
                definition = connection.execute(
                    "SELECT type, sql FROM sqlite_master WHERE name = ?", (table,),
                ).fetchone()
                if not definition or definition[0] != "table" or "VIRTUAL" in definition[1].upper():
                    _incompatible()
                if [row[1] for row in connection.execute(f"PRAGMA table_info({table})")] != columns:
                    _incompatible()
            observations = []
            total_bytes = 0
            cursor = connection.execute(
                "SELECT conversation_id, revision, export_sha256, export_uri, "
                "length(CAST(normalized_json AS BLOB)), "
                "CASE WHEN length(CAST(normalized_json AS BLOB)) <= ? THEN normalized_json END, "
                "EXISTS (SELECT 1 FROM exports e WHERE e.sha256 = observations.export_sha256), "
                "EXISTS (SELECT 1 FROM revisions r WHERE r.conversation_id = observations.conversation_id "
                "AND r.revision = observations.revision) "
                "FROM observations LIMIT ?",
                (MAX_RECORD_BYTES, MAX_OBSERVATIONS + 1),
            )
            for row in cursor:
                if len(observations) == MAX_OBSERVATIONS:
                    raise ConversationLibraryError("limit_exceeded", "More than 256 observations; no partial output.", 413)
                if row[4] is None or row[5] is None:
                    raise ConversationLibraryError("limit_exceeded", "Observation exceeds 256 KiB or is null.", 413)
                total_bytes += row[4]
                if total_bytes > MAX_TOTAL_BYTES:
                    raise ConversationLibraryError("limit_exceeded", "Observations exceed 4 MiB; no partial output.", 413)
                if not isinstance(row[5], str) or not all(isinstance(item, str) for item in row[:4]):
                    _incompatible()
                if row[6:] != (1, 1):
                    _incompatible()
                observations.append(_validate_record(row[5], row[:4]))
        if before != _file_state(path):
            raise ConversationLibraryError("library_changed", "Library changed during read; retry with producer closed.")
        observations.sort(key=lambda item: (
            item["id"], item["revision"], item["provenance"]["export_sha256"], item["provenance"]["export_uri"],
        ))
        snapshot = _digest(observations)
    except ConversationLibraryError:
        raise
    except (OSError, sqlite3.Error):
        raise ConversationLibraryError(
            "unavailable", "Selected library is unavailable, unreadable, corrupt, or exceeded the query budget.", 503,
        ) from None
    except (ValueError, TypeError, RecursionError):
        _incompatible()
    if expected_snapshot is not None and snapshot != expected_snapshot:
        raise ConversationLibraryError(
            "stale_snapshot", "Library observations differ from the expected snapshot; review again before reuse.",
        )
    return {
        "mode": "read-only-conversation-library",
        "contract": {"project": "PRJ-0006", "schema_version": SCHEMA_VERSION, "producer_revision": PRODUCER_REVISION},
        "library": str(path),
        "read_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_sha256": snapshot,
        "snapshot_check": "matches" if expected_snapshot is not None else "not_requested",
        "source_freshness": "unknown",
        "diagnostics": [
            "Imported snapshots do not establish original-source availability or freshness; export URIs are not followed.",
            "All observations and revisions are retained; none is selected as current or merged across sources.",
            "Draft producer boundary; synthetic compatibility is not real-history or product acceptance.",
        ],
        "observations": observations,
    }
