"""Bounded, deterministic adapters for explicitly supplied material."""

from __future__ import annotations

import ast
from collections import Counter
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import math
from pathlib import PurePosixPath
import re
import stat
from typing import Any
import warnings
import zipfile
import zlib

from .contract import Digestion, MaterialReference
from .safety import SECRET_RE

MAX_INPUT_BYTES = 32 * 1024
MAX_MEMBER_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 128 * 1024
MAX_MEMBERS = 32
MAX_RATIO = 100
MAX_ITEMS = 64
MAX_OBSERVATIONS = 256
MAX_GROUPS = 30
MAX_JSON_RECORDS = 512
MAX_JSON_DEPTH = 16
MAX_JSON_POINTER_CHARS = 300
FORMATS = ("text", "markdown", "csv", "html", "json", "python", "zip")
EXTENSIONS = {".txt": "text", ".md": "markdown", ".csv": "csv", ".html": "html",
              ".htm": "html", ".json": "json", ".py": "python", ".zip": "zip"}
EXTRACTOR = "dncp-supplied-material-v1"
INTENT = re.compile(r"^(?:[-*]\s*)?(TODO|FIXME|goal|intent|direction|decision|purpose)\s*:\s*(.+)", re.I)
SENSITIVE_NAME = re.compile(r"(?i)(^\.env(?:\.|$)|secret|credential|private.?key|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa$|^id_ed25519$)")
SENSITIVE_JSON_FIELD = re.compile(
    r"(?i)(?:password|passwd|secret|token|credential|api[_-]?key|private[_-]?key|authorization|access[_-]?key)"
)


class MaterialError(ValueError):
    """Invalid or unsupported material input."""


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


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result or "\0" in key:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant: {value}")


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
        json_record_count = 0
        tokens = set(re.findall(r"[a-z0-9_]+", target.lower()))
        gaps: list[dict[str, Any]] = []

        def gap(path: str, reason: str, json_pointer: str | None = None, count: int = 1) -> None:
            omissions[reason] += count
            if len(gaps) < 64:
                record = {"path": path, "reason": reason}
                if json_pointer is not None:
                    encoded_pointer = json_pointer.encode("utf-8", "surrogatepass")
                    record["json_pointer"] = json_pointer[:MAX_JSON_POINTER_CHARS]
                    if len(json_pointer) > MAX_JSON_POINTER_CHARS:
                        record["json_pointer_sha256"] = hashlib.sha256(encoded_pointer).hexdigest()
                        record["json_pointer_truncated"] = True
                gaps.append(record)
            else:
                omissions["gap_reference_limit"] += 1

        def emit(text: str, evidence: dict[str, Any], line: int | None, category: str = "",
                 json_pointer: str | None = None, preserve_whitespace: bool = False) -> None:
            nonlocal observation_count
            normalized = text if preserve_whitespace else " ".join(text.split())
            if not normalized:
                return
            if observation_count >= MAX_OBSERVATIONS:
                omissions["observation_limit"] += 1
                return
            observation_count += 1
            ref = {**evidence, "location_precision": "line" if json_pointer is None else "json_pointer"}
            if line is not None:
                ref["line"] = line
            if json_pointer is not None:
                encoded_pointer = json_pointer.encode("utf-8", "surrogatepass")
                ref["json_pointer"] = json_pointer[:MAX_JSON_POINTER_CHARS]
                if len(json_pointer) > MAX_JSON_POINTER_CHARS:
                    ref["json_pointer_sha256"] = hashlib.sha256(encoded_pointer).hexdigest()
                    ref["json_pointer_truncated"] = True
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
            if json_pointer is not None:
                identity.insert(4, json_pointer)
            result.items.append({
                "id": "MAT-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16],
                "category": category, "title": normalized[:200], "detail": normalized[:300],
                "title_truncated": len(normalized) > 200, "detail_truncated": len(normalized) > 300,
                "provenance": ref, "status": "provisional", "target_match": match,
            })

        def extract(raw: bytes, path: str, format: str) -> None:
            nonlocal json_record_count
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
                elif format == "json":
                    try:
                        document = json.loads(
                            text,
                            object_pairs_hook=_unique_json_object,
                            parse_constant=_reject_json_constant,
                        )
                    except (json.JSONDecodeError, ValueError, RecursionError):
                        gap(path, "json_parse_failed")
                        return

                    pending: list[tuple[Any, str, int]] = [(document, "", 0)]
                    while pending:
                        value, pointer, depth = pending.pop()
                        if json_record_count >= MAX_JSON_RECORDS:
                            gap(path, "json_record_limit", pointer)
                            for _, skipped_pointer, _ in pending:
                                gap(path, "json_record_limit", skipped_pointer)
                            break
                        json_record_count += 1
                        if depth > MAX_JSON_DEPTH:
                            gap(path, "json_depth_limit", pointer)
                            continue

                        if isinstance(value, dict):
                            description = f"JSON object with {len(value)} members"
                            category = "json_object"
                            children = []
                            for key in sorted(value):
                                child_pointer = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                                if SECRET_RE.search(key):
                                    gap(path, "recognized_secret_content")
                                elif SENSITIVE_JSON_FIELD.search(key):
                                    gap(path, "sensitive_field", child_pointer)
                                else:
                                    children.append((value[key], child_pointer, depth + 1))
                        elif isinstance(value, list):
                            description = f"JSON array with {len(value)} items"
                            category = "json_array"
                            children = [(child, f"{pointer}/{index}", depth + 1)
                                        for index, child in enumerate(value)]
                        else:
                            if isinstance(value, str) and "\0" in value:
                                gap(path, "binary_content", pointer)
                                continue
                            if isinstance(value, str) and SECRET_RE.search(value):
                                gap(path, "recognized_secret_content")
                                continue
                            if isinstance(value, float) and not math.isfinite(value):
                                gap(path, "json_number_out_of_range", pointer)
                                continue
                            description = json.dumps(
                                value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
                            )
                            category = "json_value"
                            children = []
                        emit(description, evidence, None, category, pointer, preserve_whitespace=True)

                        available = max(0, MAX_JSON_RECORDS - json_record_count - len(pending))
                        if len(children) > available:
                            gap(path, "json_record_limit", pointer, len(children) - available)
                            children = children[:available]
                        pending.extend(reversed(children))
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
                raise MaterialError("ZIP malformed or unreadable") from exc
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
            "observations": observation_count, "json_records": json_record_count,
            "full_semantic_coverage": False,
            "limits": {"input_bytes": MAX_INPUT_BYTES, "member_bytes": MAX_MEMBER_BYTES,
                       "total_uncompressed_bytes": MAX_TOTAL_BYTES, "members": MAX_MEMBERS,
                       "compression_ratio": MAX_RATIO, "items": MAX_ITEMS,
                       "observations": MAX_OBSERVATIONS, "observation_groups": MAX_GROUPS,
                       "references_per_group": 3, "gap_references": 64,
                       "json_records": MAX_JSON_RECORDS, "json_depth": MAX_JSON_DEPTH,
                       "json_pointer_chars": MAX_JSON_POINTER_CHARS},
            "exclusions": dict(sorted(omissions.items())), "gaps": gaps,
            "direction": "Explicit labeled declarations only; no inferred intent, authority or trust.",
            "execution": False, "external_requests": False,
        }
        return result


def digest_material(
    raw: bytes,
    *,
    name: str,
    format: str,
    identity: str | None = None,
    target: str = "",
) -> Digestion:
    """Digest explicit bytes without intake, persistence, discovery, or execution."""
    validated_name = _field(name, "name", 200, True)
    validated_identity = _field(identity if identity is not None else validated_name, "identity", 1000, True)
    digester = SuppliedMaterialDigester(raw, validated_name, format)
    reference = MaterialReference(
        kind=format,
        identity=validated_identity,
        revision=hashlib.sha256(raw).hexdigest(),
        location=validated_name,
    )
    return digester.digest(reference, target)
