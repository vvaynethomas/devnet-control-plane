"""Opt-in, deterministic repository evidence extraction; no adoption or source writes."""

from __future__ import annotations

import ast
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import threading
from typing import Any

from . import DEFAULT_DATA_DIR, PACKAGE_VERSION
from .capabilities import _module_details
from .fabric import FabricIndex, SECRET_RE

EXTRACTOR = "dncp-repository-static-v1"
MAX_TREE_BYTES = 1024 * 1024
MAX_FILES = 100
MAX_FILE_BYTES = 128 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_ITEMS = 100
MAX_RESIDUE = 30
MAX_COMPARISONS = 10
MAX_OBSERVATIONS = 1000
EXCLUDED_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__"}
MANIFESTS = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements.txt"}
CONFIGS = {"Dockerfile", "Makefile", ".editorconfig"}
SENSITIVE = re.compile(r"(?i)(^\.env(?:\.|$)|secret|credential|private.?key|\.pem$|\.key$)")
NOTICE = "Provisional human-review evidence only: similarity is not trust; no match is not novelty."
PROPOSAL_OPTIONS = ["existing capability", "potential solution: suitability/trust review",
                    "customize/extend/integrate", "new knowledge/idea", "defer", "reject"]


class DigesterError(ValueError):
    pass


def _git(repo: Path, *args: str, limit: int = MAX_TREE_BYTES) -> bytes:
    """Bound output/time of read-only plumbing; never invoke hooks, filters, or repo code."""
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"})
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment) as process:
        timer = threading.Timer(10, process.kill)
        timer.start()
        try:
            assert process.stdout is not None
            output = process.stdout.read(limit + 1)
            if len(output) > limit:
                process.kill()
                raise DigesterError(f"Git {args[0]} output exceeded {limit} bytes; scan refused, not silently truncated")
            code = process.wait()
            if code:
                raise DigesterError(f"Read-only Git {args[0]} failed or timed out (exit {code})")
            return output
        finally:
            timer.cancel()


def _repository(path: Path) -> Path:
    root = path.resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise DigesterError("registration requires a repository root containing a Git marker")
    observed = Path(_git(root, "rev-parse", "--show-toplevel", limit=8192).decode("utf-8").strip()).resolve()
    if observed != root:
        raise DigesterError("register the repository root, not a subdirectory")
    return root


def _safe_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or SECRET_RE.search(value):
        raise DigesterError(f"{name} must be a non-sensitive string of at most {maximum} characters")
    return value.strip()


class RepositoryDigester:
    """Registration is local consent metadata, never a scan trigger or agent obligation."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR, fabric: FabricIndex | None = None) -> None:
        self.data_dir = data_dir.resolve()
        for ancestor in (self.data_dir, *self.data_dir.parents):
            if (ancestor / ".git").exists():
                raise DigesterError("digester registration data must live outside Git repositories")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "digester.sqlite"
        self.fabric = fabric
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS repositories (path TEXT PRIMARY KEY, enabled INTEGER NOT NULL, registered_at TEXT NOT NULL)"
            )
            conn.commit()

    def register(self, path: Path) -> dict[str, Any]:
        root = _repository(path)
        # An explicit opt-in records only path and time; no HEAD, tree or source reads.
        timestamp = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("INSERT OR REPLACE INTO repositories VALUES (?, 1, ?)", (str(root), timestamp))
            conn.commit()
        return {"schema_version": 1, "path": str(root), "enabled": True, "registered_at": timestamp,
                "scan_performed": False, "notice": "Opt-in only; invoke scan explicitly later."}

    def disable(self, path: Path) -> dict[str, Any]:
        root = path.resolve()
        with closing(sqlite3.connect(self.db_path)) as conn:
            changed = conn.execute("UPDATE repositories SET enabled=0 WHERE path=?", (str(root),)).rowcount
            conn.commit()
        if not changed:
            raise DigesterError("repository is not registered")
        return {"path": str(root), "enabled": False, "scan_performed": False}

    def registrations(self) -> dict[str, Any]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute("SELECT path, enabled, registered_at FROM repositories ORDER BY path").fetchall()
        return {"schema_version": 1, "repositories": [
            {"path": path, "enabled": bool(enabled), "registered_at": timestamp} for path, enabled, timestamp in rows
        ]}

    def scan(self, path: Path, target: str = "") -> dict[str, Any]:
        root = path.resolve()
        target = _safe_text(target, "target", 2000)
        # Check consent BEFORE any source repository operation.
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT enabled FROM repositories WHERE path=?", (str(root),)).fetchone()
        if row is None or not row[0]:
            raise DigesterError("repository is not opted in; register explicitly before invoking scan")
        root = _repository(root)
        revision = _git(root, "rev-parse", "--verify", "HEAD^{commit}", limit=100).decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise DigesterError("Git returned an unsupported commit identity")
        tree = _git(root, "ls-tree", "-rz", "--full-tree", revision)
        inventory = []
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            meta, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = meta.decode("ascii").split()
            inventory.append((raw_path.decode("utf-8", errors="replace"), mode, kind, oid))
        inventory.sort()
        omissions: Counter[str] = Counter()
        errors: list[dict[str, str]] = []
        items: list[dict[str, Any]] = []
        item_titles: dict[str, str] = {}
        occurrences: Counter[str] = Counter()
        observation_refs: dict[str, list[dict[str, Any]]] = {}
        consumed = files_read = 0
        file_evidence: list[dict[str, Any]] = []

        def add_item(
            category: str, title: str, evidence: dict[str, Any], line: int, detail: str = "", precision: str = "line",
        ) -> None:
            if len(items) >= MAX_ITEMS:
                omissions["material_item_limit"] += 1
                return
            identity = f"{revision}:{evidence['path']}:{category}:{line}:{title}"
            item_id = "MAT-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            item_titles[item_id] = title
            omissions["material_title_truncation"] += int(len(title) > 200)
            omissions["material_detail_truncation"] += int(len(detail) > 300)
            items.append({"id": item_id,
                          "category": category, "title": title[:200], "detail": detail[:300],
                          "title_truncated": len(title) > 200, "detail_truncated": len(detail) > 300,
                          "provenance": {**evidence, "line": line, "location_precision": precision},
                          "status": "provisional"})

        def observe(text: str, evidence: dict[str, Any], line: int) -> None:
            if sum(occurrences.values()) >= MAX_OBSERVATIONS:
                omissions["observation_limit"] += 1
                return
            normalized = " ".join(text.split())
            if not normalized:
                return
            occurrences[normalized] += 1
            refs = observation_refs.setdefault(normalized, [])
            if len(refs) < 3:
                refs.append({**evidence, "line": line})
            else:
                omissions["residue_evidence_reference_limit"] += 1

        for relative, mode, kind, oid in inventory:
            p = PurePosixPath(relative)
            reason = ""
            if "\ufffd" in relative or p.is_absolute() or ".." in p.parts:
                reason = "unsupported_path"
            elif mode not in ("100644", "100755") or kind != "blob":
                reason = "symlink_submodule_or_nonregular"
            elif any(part in EXCLUDED_DIRS for part in p.parts):
                reason = "generated_vendor_or_cache"
            elif any(SENSITIVE.search(part) for part in p.parts):
                reason = "sensitive_filename"
            elif SECRET_RE.search(relative):
                reason = "recognized_secret_filename"
            elif not (p.name in MANIFESTS | CONFIGS or p.suffix in (".md", ".py")
                      or (p.parts[0] == ".github" and p.suffix in (".yml", ".yaml"))):
                reason = "unrecognized_material"
            elif files_read >= MAX_FILES:
                reason = "file_count_limit"
            if reason:
                omissions[reason] += 1
                continue
            try:
                size = int(_git(root, "cat-file", "-s", oid, limit=100))
                if size > MAX_FILE_BYTES:
                    omissions["file_size_limit"] += 1
                    continue
                if consumed + size > MAX_TOTAL_BYTES:
                    omissions["total_byte_limit"] += 1
                    continue
                raw = _git(root, "cat-file", "blob", oid, limit=MAX_FILE_BYTES)
                consumed += len(raw)
                files_read += 1
                text = raw.decode("utf-8")
                if "\0" in text:
                    omissions["binary_content"] += 1
                    continue
                if SECRET_RE.search(text):
                    omissions["recognized_secret_content"] += 1
                    continue
                evidence = {"path": relative, "revision": revision, "git_blob": oid,
                            "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                            "link": f"git:{revision}:{relative}"}
                file_evidence.append(evidence)
                if p.suffix == ".py":
                    doc, symbols = _module_details(text)
                    nodes = ast.parse(text)
                    add_item("python_module", p.as_posix(), evidence, 1, doc, "file")
                    for node in nodes.body:
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in symbols:
                            add_item("python_symbol", node.name, evidence, node.lineno)
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                observe("import " + alias.name, evidence, node.lineno)
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            observe("import " + node.module, evidence, node.lineno)
                elif p.name in MANIFESTS:
                    add_item("dependency_manifest", p.name, evidence, 1, "Observed declaration; not an SBOM or installed dependency inventory.", "file")
                    if p.name == "package.json":
                        manifest = json.loads(text)
                        if not isinstance(manifest, dict):
                            raise ValueError("manifest must be an object")
                        for group in ("dependencies", "devDependencies", "peerDependencies"):
                            deps = manifest.get(group, {})
                            if not isinstance(deps, dict):
                                raise ValueError("dependency groups must be objects")
                            for name, version in sorted(deps.items()):
                                add_item("dependency_declaration", str(name), evidence, 1, str(version), "file")
                    else:
                        for line, value in enumerate(text.splitlines(), 1):
                            if value.strip() and not value.lstrip().startswith("#"):
                                observe(f"{p.name}: {value}", evidence, line)
                elif p.suffix == ".md":
                    for line, value in enumerate(text.splitlines(), 1):
                        if value.startswith("#"):
                            add_item("document_heading", value.lstrip("#").strip(), evidence, line)
                        elif re.search(r"\b(TODO|FIXME|idea|decision|limitation|warning)\b", value, re.I):
                            observe(value, evidence, line)
                else:
                    add_item("configuration", p.as_posix(), evidence, 1, "Static configuration evidence only; never executed.", "file")
                    for line, value in enumerate(text.splitlines(), 1):
                        if re.search(r"\b(TODO|FIXME|warning)\b", value, re.I):
                            observe(value, evidence, line)
            except (OSError, ValueError, UnicodeError, SyntaxError, RecursionError) as exc:
                # Never echo parser exception text containing source snippets.
                errors.append({"path": relative, "error": type(exc).__name__, "detail": "Static extraction failed; source content not echoed."})

        tokens = set(re.findall(r"[a-z0-9_]+", target.lower()))
        for item in items:
            blob = f"{item['title']} {item['detail']}".lower()
            item["target_match"] = bool(tokens and any(t in blob for t in tokens))
            if target and not item["target_match"]:
                observe(f"Untargeted {item['category']}: {item_titles[item['id']]}", item["provenance"], item["provenance"]["line"])
        residue = []
        for observation, count in sorted(occurrences.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_RESIDUE]:
            if len(observation) > 300:
                omissions["residue_text_truncation"] += 1
            residue.append({"observation": observation[:300], "observation_sha256": hashlib.sha256(observation.encode()).hexdigest(),
                            "text_truncated": len(observation) > 300, "count": count, "evidence": observation_refs[observation],
                            "interpretation": "Observed occurrences in this revision only; frequency is not independence, corroboration, or trust."})
        omissions["residue_group_limit"] += max(0, len(occurrences) - MAX_RESIDUE)
        comparisons, coverage = self._compare(items, target)
        payload = {
            "schema_version": 1, "material": {"type": "repository", "reference": str(root), "revision": revision,
                                              "view": "committed HEAD only; dirty/untracked working files excluded"},
            "extractor": {"name": EXTRACTOR, "version": PACKAGE_VERSION, "git_version": _git(root, "--version", limit=200).decode().strip()},
            "items": items, "file_evidence": file_evidence,
            "coverage": {"tree_entries": len(inventory), "files_read": files_read, "bytes_read": consumed,
                         "limits": {"files": MAX_FILES, "file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES,
                                    "items": MAX_ITEMS, "residue_groups": MAX_RESIDUE, "observations": MAX_OBSERVATIONS,
                                    "tree_bytes": MAX_TREE_BYTES, "comparison_queries": MAX_COMPARISONS},
                         "exclusions": dict(sorted(omissions.items())), "errors": errors,
                         "full_repository_coverage": False, "dependencies": "Declarations only; no resolved SBOM",
                         "symbol_graph": "Bounded Python top-level AST only; no cross-language symbol graph"},
            "residue": {"items": residue, "retention": "Returned bounded bundle only; no source copies or scan history retained.",
                        "note": "Notable untargeted/repeated static observations, not fabricated discoveries."},
            "comparison": {"inventory": coverage, "proposals": comparisons},
            "review": {"status": "provisional", "notice": NOTICE, "options": PROPOSAL_OPTIONS,
                       "destination": "Chosen by the human/destination product owner; incubator is optional.",
                       "automatic_adoption": False, "automatic_phone_home": False},
            "target": target,
        }
        payload["evidence_digest"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        payload["observed_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    def _compare(self, items: list[dict[str, Any]], target: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        comparison_errors = []
        try:
            freshness = self.fabric.freshness() if self.fabric else {"built": False}
        except (OSError, sqlite3.Error, ValueError) as exc:
            freshness = {"built": False}
            comparison_errors.append({"error": type(exc).__name__, "detail": "Existing Fabric cache unavailable; not rebuilt."})
        coverage = {"available": bool(freshness["built"]), "fabric": freshness,
                    "scope": "Existing Fabric cache only; no live repository, registry, personal-chat or module scans.",
                    "full_product_library_graph": False, "errors": comparison_errors,
                    "unknowns": ["Product libraries/releases are not federated.", "No match does not establish novelty.",
                                 "Similarity does not establish trust, suitability, or operational readiness."]}
        proposals = []
        selected = sorted(items, key=lambda item: (not item["target_match"], item["id"]))[:MAX_COMPARISONS]
        for item in selected:
            query = target if target and item["target_match"] else item["title"]
            query = " ".join(re.findall(r"[A-Za-z0-9_-]+", query)[:12])
            matches = []
            if freshness["built"] and query:
                assert self.fabric is not None
                try:
                    matches = self.fabric.search(query, limit=5, initialize=False)["results"]
                except (OSError, sqlite3.Error, ValueError) as exc:
                    coverage["available"] = False
                    comparison_errors.append({"error": type(exc).__name__, "detail": "Cached comparison failed; no source scan or rebuild performed."})
            proposals.append({
                "material_item_id": item["id"], "query": query, "matches": matches, "status": "provisional",
                "proposal": "potential solution: existing capability/customize/extend/integrate review" if matches else "new knowledge/idea candidate: incomplete inventory review",
                "rationale": "FTS text relevance against cached evidence only." if matches else "No available cached match; novelty and trust unresolved.",
                "review_options": PROPOSAL_OPTIONS,
                "evidence": item["provenance"],
            })
        coverage["items_compared"] = len(selected)
        coverage["items_not_compared"] = len(items) - len(selected)
        return proposals, coverage
