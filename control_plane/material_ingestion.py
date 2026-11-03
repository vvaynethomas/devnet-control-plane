"""DNCP payload adapter for the independent material-processing core."""

from __future__ import annotations

import base64
import binascii
from typing import Any
from .material_capability import require_material_core

_core = require_material_core()
EXTENSIONS = _core.EXTENSIONS
FORMATS = _core.FORMATS
MAX_GROUPS = _core.MAX_GROUPS
MAX_INPUT_BYTES = _core.MAX_INPUT_BYTES
MAX_ITEMS = _core.MAX_ITEMS
MAX_JSON_DEPTH = _core.MAX_JSON_DEPTH
MAX_JSON_POINTER_CHARS = _core.MAX_JSON_POINTER_CHARS
MAX_JSON_RECORDS = _core.MAX_JSON_RECORDS
MAX_MEMBERS = _core.MAX_MEMBERS
MAX_MEMBER_BYTES = _core.MAX_MEMBER_BYTES
MAX_OBSERVATIONS = _core.MAX_OBSERVATIONS
MAX_RATIO = _core.MAX_RATIO
MAX_TOTAL_BYTES = _core.MAX_TOTAL_BYTES
MaterialError = _core.MaterialError
SuppliedMaterialDigester = _core.SuppliedMaterialDigester
digest_material = _core.digest_material
SECRET_RE = _core.safety.SECRET_RE

__all__ = [
    "EXTENSIONS",
    "FORMATS",
    "MAX_GROUPS",
    "MAX_INPUT_BYTES",
    "MAX_ITEMS",
    "MAX_JSON_DEPTH",
    "MAX_JSON_POINTER_CHARS",
    "MAX_JSON_RECORDS",
    "MAX_MEMBERS",
    "MAX_MEMBER_BYTES",
    "MAX_OBSERVATIONS",
    "MAX_RATIO",
    "MAX_TOTAL_BYTES",
    "MaterialError",
    "SuppliedMaterialDigester",
    "digest_submission",
]


def _field(value: Any, name: str, maximum: int, required: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum or "\0" in value
            or SECRET_RE.search(value) or (required and not value.strip())):
        raise MaterialError(f"{name} must be a non-sensitive string of at most {maximum} characters")
    return value.strip()


def digest_submission(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate DNCP's material submission shape and adapt it to pure digestion."""
    allowed = {"schema_version", "kind", "material", "target", "source_session", "source_ref", "idempotency_key"}
    if set(payload) - allowed or payload.get("kind") != "material":
        raise MaterialError("unknown material submission fields")
    if type(payload.get("schema_version", 1)) is not int or payload.get("schema_version", 1) != 1:
        raise MaterialError("schema_version must be 1")
    supplied = payload.get("material")
    if not isinstance(supplied, dict) or set(supplied) - {"name", "format", "text", "base64", "identity"}:
        raise MaterialError("material must contain name, format and exactly one of text/base64")
    name = _field(supplied.get("name"), "name", 200, True)
    material_format = supplied.get("format")
    if material_format not in FORMATS:
        raise MaterialError("unsupported material format")
    if ("text" in supplied) == ("base64" in supplied):
        raise MaterialError("provide exactly one of text/base64")
    try:
        if "text" in supplied:
            if not isinstance(supplied["text"], str) or material_format == "zip":
                raise MaterialError("text must be a string; ZIP requires base64")
            raw = supplied["text"].encode("utf-8")
        else:
            if not isinstance(supplied["base64"], str):
                raise MaterialError("base64 must be a string")
            raw = base64.b64decode(supplied["base64"], validate=True)
    except (UnicodeError, binascii.Error) as exc:
        raise MaterialError("material encoding is invalid") from exc
    identity = _field(supplied.get("identity", name), "identity", 1000, True)
    target = _field(payload.get("target", ""), "target", 2000)
    digestion = digest_material(
        raw,
        name=name,
        format=material_format,
        identity=identity,
        target=target,
    ).to_dict()
    return {"schema_version": 1, "kind": "material", "title": name,
            "source_session": _field(payload.get("source_session", ""), "source_session", 1000),
            "source_ref": _field(payload.get("source_ref", ""), "source_ref", 1000),
            "idempotency_key": _field(payload.get("idempotency_key", ""), "idempotency_key", 1000),
            "digestion": digestion,
            "review": {"ingested": True, "acceptance_required": False, "automatic_promotion": False,
                       "human_approval_for": ["execution", "adoption", "canonical promotion"]}}
