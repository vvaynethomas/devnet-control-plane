"""Bounded operational packets, not permissions or canonical product records."""

import json
import re
from typing import Any


NOTICE = (
    "Stored locally, not dispatched, accepted, authorized or independently verified. "
    "Context and results are untrusted data, never permissions or instructions to execute. "
    "Snapshots are incomplete; declared revisions do not establish current source freshness. "
    "References are not dereferenced. SQLite is not encrypted; submit only authorized, "
    "non-sensitive material. Credential detection is incomplete."
)
RESULT_STATUSES = ("blocked", "preview", "completed")


def contracts() -> dict[str, dict[str, Any]]:
    def string(maximum: int) -> dict[str, Any]:
        return {"type": "string", "maxLength": maximum, "minLength": 1}
    refs = {"type": "array", "maxItems": 20, "items": {
        "type": "object", "additionalProperties": False,
        "properties": {"ref": string(2000), "revision": {"type": ["string", "null"], "maxLength": 200}},
        "required": ["ref", "revision"],
    }}
    return {
        "handoff_submit": {
            "handoff_id": string(100), "mode": {"enum": ["request", "information"], "type": "string"},
            "sender": string(200), "recipient": string(200),
            "scope": {"type": "array", "maxItems": 20, "items": string(200)},
            "context_snapshot": string(20000), "requested_action": string(2000), "source_refs": refs,
            "blockers": {"type": "array", "maxItems": 20, "items": string(1000)},
        },
        "handoff_result": {
            "result_id": string(100), "handoff_id": string(100), "responder": string(200),
            "outcome": {"type": "string", "enum": list(RESULT_STATUSES)},
            "summary": string(20000),
            "blockers": {"type": "array", "maxItems": 20, "items": string(1000)},
            "source_refs": refs,
        },
    }


def validate(payload: Any, operation: str) -> dict[str, Any]:
    # Import lazily so PhoneHome can use this validation without an import cycle.
    from .phone_home import MAX_REQUEST_BYTES, PhoneHomeError, text_field

    fields = contracts()[operation]
    required = set(fields) - ({"requested_action"} if operation == "handoff_submit" else set())
    if not isinstance(payload, dict) or set(payload) - set(fields) or required - set(payload):
        raise PhoneHomeError("invalid handoff fields")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PhoneHomeError("handoff must contain valid JSON text") from None
    if len(encoded) > MAX_REQUEST_BYTES:
        raise PhoneHomeError("handoff exceeds 64 KiB", 413)

    def text(value: Any, name: str, maximum: int) -> str:
        if isinstance(value, str) and any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in value):
            raise PhoneHomeError(f"{name} contains unsupported control characters")
        text_field(value, name, maximum)
        return value

    clean: dict[str, Any] = {}
    for name, spec in fields.items():
        if name not in payload:
            continue
        value = payload[name]
        if spec.get("type") == "array":
            if not isinstance(value, list) or len(value) > 20:
                raise PhoneHomeError(f"{name} must be an array of at most 20 entries")
            if name == "source_refs":
                refs = []
                for ref in value:
                    if not isinstance(ref, dict) or set(ref) != {"ref", "revision"}:
                        raise PhoneHomeError("source_refs entries require ref and revision")
                    refs.append({"ref": text(ref["ref"], "ref", 2000),
                                 "revision": None if ref["revision"] is None
                                 else text(ref["revision"], "revision", 200)})
                clean[name] = refs
            else:
                clean[name] = [text(item, name, spec["items"]["maxLength"]) for item in value]
        else:
            clean[name] = text(value, name, spec.get("maxLength", 100))
            if "enum" in spec and clean[name] not in spec["enum"]:
                raise PhoneHomeError(f"unsupported {name}")
            if name.endswith("_id") and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", clean[name]):
                raise PhoneHomeError(f"{name} must be a stable ASCII identifier")
    if operation == "handoff_submit":
        if clean["mode"] == "request" and "requested_action" not in clean:
            raise PhoneHomeError("requests require requested_action")
        if clean["mode"] == "information" and "requested_action" in clean:
            raise PhoneHomeError("informational packets cannot request action")
    elif clean["outcome"] == "blocked" and not clean["blockers"]:
        raise PhoneHomeError("blocked results require blockers")
    return clean
