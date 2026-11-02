"""Bounded local adapters for explicitly supplied material; never execute or fetch."""

from __future__ import annotations

import ast
import base64
import binascii
from collections import Counter
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import PurePosixPath
import re
import stat
from typing import Any
import warnings
import zipfile
import zlib

from .digester import Digestion, MaterialReference
from .fabric import SECRET_RE

MAX_INPUT_BYTES = 32 * 1024
MAX_MEMBER_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 128 * 1024
MAX_MEMBERS = 32
MAX_RATIO = 100
MAX_ITEMS = 64
MAX_OBSERVATIONS = 256
MAX_GROUPS = 30
FORMATS = ("text", "markdown", "csv", "html", "python", "zip")
EXTENSIONS = {".txt": "text", ".md": "markdown", ".csv": "csv", ".html": "html",
              ".htm": "html", ".py": "python", ".zip": "zip"}
EXTRACTOR = "dncp-supplied-material-v1"
INTENT = re.compile(r"^(?:[-*]\s*)?(TODO|FIXME|goal|intent|direction|decision|purpose)\s*:\s*(.+)", re.I)
SENSITIVE_NAME = re.compile(r"(?i)(^\.env(?:\.|$)|secret|credential|private.?key|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa$|^id_ed25519$)")


class MaterialError(ValueError):
    status = 400


def _field(value: Any, name: str, maximum: int, required: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum or "\0" in value
            or SECRET_RE.search(value) or (required and not value.strip())):
        raise MaterialError(f"{name} must be a non-sensitive string of at most {maximum} characters")
    return value.strip()


def _safe_member(name: str) -> bool:
    parts = name.rstrip("/").split("/")
    return bool(name and len(name) <= 500 and not name.startswith("/") and "\\" not in name
                and all(part not in ("", ".", "..") and not part.endswith((".", " "))
                        and not re.search(r'[:<>"|?*\x00-\x1f\x7f]', part)
                        and not re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part)
                        for part in parts))


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[tuple[int, str]] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "template") and tag not in self.hidden:
            self.hidden.append(tag)
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden:
            self.hidden.remove(tag)

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append((self.getpos()[0], data.strip()))


class SuppliedMaterialDigester:
    """Implements the shared pure Digester contract over an already bounded byte input."""

    def __init__(self, raw: bytes, name: str, format: str) -> None:
        if not isinstance(raw, bytes) or len(raw) > MAX_INPUT_BYTES:
            raise MaterialError("material exceeds 32 KiB or is not bytes")
        self.raw = raw
        self.name = _field(name, "name", 200, True)
        if format not in FORMATS:
            raise MaterialError("unsupported material format")
        self.format = format

    def digest(self, material: MaterialReference, target: str = "") -> Digestion:
        revision = hashlib.sha256(self.raw).hexdigest()
        if material.kind != self.format or material.revision != revision:
            raise MaterialError("material kind/revision must match the supplied bytes")
        for value in (material.identity, material.location):
            _field(value, "material reference", 1000, True)
        target = _field(target, "target", 2000)
        result = Digestion(material, [{"name": EXTRACTOR, "version": "1"}], target=target)
        omissions: Counter[str] = Counter()
        observations: dict[str, dict[str, Any]] = {}
        observation_count = 0
        tokens = set(re.findall(r"[a-z0-9_]+", target.lower()))
        gaps: list[dict[str, Any]] = []

        def gap(path: str, reason: str) -> None:
            omissions[reason] += 1
            if len(gaps) < 64:
                gaps.append({"path": path, "reason": reason})
            else:
                omissions["gap_reference_limit"] += 1

        def emit(text: str, evidence: dict[str, Any], line: int, category: str = "") -> None:
            nonlocal observation_count
            normalized = " ".join(text.split())
            if not normalized:
                return
            if observation_count >= MAX_OBSERVATIONS:
                omissions["observation_limit"] += 1
                return
            observation_count += 1
            ref = {**evidence, "line": line, "location_precision": "line"}
            match = bool(tokens and any(token in normalized.lower() for token in tokens))
            key = hashlib.sha256(normalized.encode()).hexdigest()
            group = observations.setdefault(key, {
                "observation": normalized[:300], "observation_sha256": key,
                "text_truncated": len(normalized) > 300, "count": 0, "evidence": [],
                "target_match": match, "extracted_item": bool(category),
            })
            group["count"] += 1
            group["extracted_item"] = group["extracted_item"] or bool(category)
            if len(group["evidence"]) < 3:
                group["evidence"].append(ref)
            else:
                omissions["observation_reference_limit"] += 1
            if not category:
                return
            if len(result.items) >= MAX_ITEMS:
                omissions["item_limit"] += 1
                return
            identity = [material.identity, revision, evidence["path"], line, category, normalized]
            result.items.append({
                "id": "MAT-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16],
                "category": category, "title": normalized[:200], "detail": normalized[:300],
                "title_truncated": len(normalized) > 200, "detail_truncated": len(normalized) > 300,
                "provenance": ref, "status": "provisional", "target_match": match,
            })

        def extract(raw: bytes, path: str, format: str) -> None:
            evidence = {"path": path, "identity": material.identity, "revision": revision,
                        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                        "extractor": EXTRACTOR, "extractor_version": "1",
                        "container_sha256": revision if self.format == "zip" else None}
            result.file_evidence.append(evidence)
            if any(SENSITIVE_NAME.search(part) for part in PurePosixPath(path).parts):
                gap(path, "sensitive_filename")
                return
            try:
                text = raw.decode("utf-8-sig")
                if "\0" in text:
                    gap(path, "binary_content")
                    return
                if SECRET_RE.search(text):
                    gap(path, "recognized_secret_content")
                    return
                if format == "python":
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        tree = ast.parse(text)
                    selected: dict[int, str] = {}
                    for node in tree.body:
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            selected[node.lineno] = "python_symbol"
                    for line, value in enumerate(text.splitlines(), 1):
                        category = selected.get(line, "")
                        emit(value, evidence, line, category)
                    gap(path, "python_semantics_not_evaluated")
                elif format == "csv":
                    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
                    header = next(reader, None)
                    if header is not None:
                        emit(json.dumps(header, ensure_ascii=False), evidence, 1, "csv_header")
                        start = reader.line_num + 1
                        for row in reader:
                            if len(row) != len(header):
                                gap(path, "csv_ragged_row")
                            emit(json.dumps(row, ensure_ascii=False), evidence, start, "csv_row")
                            for column, value in zip(header, row):
                                if column.strip().lower() in ("goal", "intent", "direction", "purpose", "decision"):
                                    emit(f"{column}: {value}", evidence, start, "declared_direction")
                            start = reader.line_num + 1
                    gap(path, "csv_types_and_dialect_not_inferred")
                elif format == "html":
                    parser = _HTML()
                    parser.feed(text)
                    parser.close()
                    for line, value in parser.parts:
                        emit(value, evidence, line, "declared_direction" if INTENT.match(value) else "html_text")
                    omissions["html_hidden_regions"] += parser.ignored
                    gap(path, "html_markup_attributes_comments_not_interpreted")
                else:
                    fence: str | None = None
                    for line, value in enumerate(text.splitlines(), 1):
                        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", value) if format == "markdown" else None
                        category = ""
                        if marker:
                            if fence is None:
                                fence = marker[1]
                            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                                fence = None
                        elif fence is None:
                            if INTENT.match(value.strip()):
                                category = "declared_direction"
                            elif format == "markdown" and re.match(r"^ {0,3}#{1,6}\s+\S", value):
                                category = "document_heading"
                            elif format == "text":
                                category = "text_observation"
                        emit(value, evidence, line, category)
                    if format == "markdown":
                        gap(path, "markdown_semantics_links_and_embedded_content_not_interpreted")
            except (UnicodeError, SyntaxError, csv.Error, RecursionError, ValueError):
                gap(path, "static_parse_failed")

        if self.format == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(self.raw)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_MEMBERS:
                        raise MaterialError("ZIP exceeds 32 members")
                    seen: set[str] = set()
                    total = 0
                    for member in members:
                        name = member.filename
                        mode = member.external_attr >> 16
                        if (not _safe_member(name) or member.orig_filename != name
                                or name.rstrip("/").casefold() in seen or SECRET_RE.search(name)):
                            raise MaterialError("ZIP contains unsafe or duplicate paths")
                        seen.add(name.rstrip("/").casefold())
                        if member.flag_bits & 1 or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                            raise MaterialError("ZIP encrypted or nonregular member refused")
                        if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                            raise MaterialError("ZIP compression method unsupported")
                        total += member.file_size
                        if (member.file_size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES
                                or member.file_size > MAX_RATIO * max(1, member.compress_size)):
                            raise MaterialError("ZIP size or compression ratio limit exceeded")
                    for member in members:
                        if member.is_dir():
                            continue
                        format = EXTENSIONS.get(PurePosixPath(member.filename).suffix.lower())
                        if format is None or format == "zip":
                            gap(member.filename, "unsupported_or_nested_container")
                            continue
                        with archive.open(member) as source:
                            raw = source.read(MAX_MEMBER_BYTES + 1)
                        if len(raw) > MAX_MEMBER_BYTES or len(raw) != member.file_size:
                            raise MaterialError("ZIP member size mismatch")
                        extract(raw, member.filename, format)
            except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, OSError, UnicodeError, zlib.error) as exc:
                raise MaterialError("ZIP malformed or unreadable; no submission saved") from exc
        else:
            extract(self.raw, self.name, self.format)

        groups = sorted(observations.values(), key=lambda group: (-group["count"], group["observation_sha256"]))
        omissions["observation_group_limit"] += max(0, len(groups) - MAX_GROUPS)
        result.residue = {
            "items": groups[:MAX_GROUPS],
            "note": "All observed groups, including untargeted content. Repetition is frequency, not waste, corroboration or trust.",
            "retention": "Only bounded evidence is retained locally in the provisional inbox; raw input is not copied.",
        }
        result.coverage = {
            "input_bytes": len(self.raw), "files_read": len(result.file_evidence),
            "observations": observation_count, "full_semantic_coverage": False,
            "limits": {"input_bytes": MAX_INPUT_BYTES, "member_bytes": MAX_MEMBER_BYTES,
                       "total_uncompressed_bytes": MAX_TOTAL_BYTES, "members": MAX_MEMBERS,
                       "compression_ratio": MAX_RATIO, "items": MAX_ITEMS,
                       "observations": MAX_OBSERVATIONS, "observation_groups": MAX_GROUPS,
                       "references_per_group": 3, "gap_references": 64},
            "exclusions": dict(sorted(omissions.items())), "gaps": gaps,
            "direction": "Explicit labeled declarations only; no inferred intent, authority or trust.",
            "execution": False, "external_requests": False,
        }
        return result


def digest_submission(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"schema_version", "kind", "material", "target", "source_session", "source_ref", "idempotency_key"}
    if set(payload) - allowed or payload.get("kind") != "material":
        raise MaterialError("unknown material submission fields")
    if type(payload.get("schema_version", 1)) is not int or payload.get("schema_version", 1) != 1:
        raise MaterialError("schema_version must be 1")
    supplied = payload.get("material")
    if not isinstance(supplied, dict) or set(supplied) - {"name", "format", "text", "base64", "identity"}:
        raise MaterialError("material must contain name, format and exactly one of text/base64")
    name = _field(supplied.get("name"), "name", 200, True)
    format = supplied.get("format")
    if format not in FORMATS:
        raise MaterialError("unsupported material format")
    if ("text" in supplied) == ("base64" in supplied):
        raise MaterialError("provide exactly one of text/base64")
    try:
        if "text" in supplied:
            if not isinstance(supplied["text"], str) or format == "zip":
                raise MaterialError("text must be a string; ZIP requires base64")
            raw = supplied["text"].encode("utf-8")
        else:
            if not isinstance(supplied["base64"], str):
                raise MaterialError("base64 must be a string")
            raw = base64.b64decode(supplied["base64"], validate=True)
    except (UnicodeError, binascii.Error) as exc:
        raise MaterialError("material encoding is invalid") from exc
    identity = _field(supplied.get("identity", name), "identity", 1000, True)
    reference = MaterialReference(format, identity, hashlib.sha256(raw).hexdigest(), name)
    target = _field(payload.get("target", ""), "target", 2000)
    digestion = SuppliedMaterialDigester(raw, name, format).digest(reference, target).to_dict()
    return {"schema_version": 1, "kind": "material", "title": name,
            "source_session": _field(payload.get("source_session", ""), "source_session", 1000),
            "source_ref": _field(payload.get("source_ref", ""), "source_ref", 1000),
            "idempotency_key": _field(payload.get("idempotency_key", ""), "idempotency_key", 1000),
            "digestion": digestion,
            "review": {"ingested": True, "acceptance_required": False, "automatic_promotion": False,
                       "human_approval_for": ["execution", "adoption", "canonical promotion"]}}
