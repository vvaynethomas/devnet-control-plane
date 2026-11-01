"""Opt-in committed-repository digestion, local evidence and human-only review."""

from __future__ import annotations

import ast
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import tempfile
from typing import Any
import uuid

from . import DEFAULT_DATA_DIR, FACTORY_ROOT, PROJECT_ROOT
from .capabilities import _module_details, discover_capabilities
from .digester import DISPOSITIONS, REVIEW_ACTIONS, Digestion, MaterialReference
from .fabric import FabricIndex, SECRET_RE, redact_secrets

MAX_TREE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 200
MAX_ITEMS = 1000
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "vendor",
    "dist", "build", ".tox", ".pytest_cache",
}
EXTRACTORS = [
    {"name": "git-tree", "version": "1"},
    {"name": "python-ast", "version": "1"},
    {"name": "json-manifest", "version": "1"},
    {"name": "requirements", "version": "1"},
    {"name": "markdown-headings", "version": "1"},
]


class MetabolizerError(ValueError):
    pass


def _text(value: Any, name: str, maximum: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\0" in value:
        raise MetabolizerError(f"{name} must be a nonempty string of at most {maximum} characters")
    if SECRET_RE.search(value):
        raise MetabolizerError(f"{name} contains a recognized credential pattern")
    return value.strip()


def _git(root: Path, *arguments: str, maximum: int = MAX_TREE_BYTES) -> bytes:
    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"):
        env.pop(name, None)
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"})
    # Spool output rather than retaining an unbounded tree in memory.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "--no-replace-objects", "-C", str(root), *arguments],
                stdout=output, stderr=subprocess.PIPE, env=env, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MetabolizerError(f"Git read failed: {exc}") from exc
        if result.returncode:
            message = redact_secrets(result.stderr.decode("utf-8", errors="replace")[:2000])
            raise MetabolizerError(f"Git read failed: {message.strip()}")
        if output.tell() > maximum:
            raise MetabolizerError(f"Git output exceeds {maximum} bytes; analysis is not complete")
        output.seek(0)
        return output.read()


def _repo_root(path: Path) -> Path:
    root = path.resolve()
    actual = Path(_git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if actual != root:
        raise MetabolizerError("register the top-level Git repository, not a subdirectory")
    return root


def _revision(root: Path, revision: str) -> str:
    ref = _text(revision, "revision")
    commit = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise MetabolizerError("revision did not resolve to a Git commit")
    return commit


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


class RepositoryDigester:
    def __init__(self, exclusions: list[str] | None = None) -> None:
        self.exclusions = exclusions or []

    def digest(self, material: MaterialReference) -> Digestion:
        if material.kind != "repository" or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", material.revision):
            raise MetabolizerError("repository digestion requires an exact commit reference")
        root = Path(material.location)
        bundle = Digestion(material, [dict(e) for e in EXTRACTORS])
        bundle.coverage.update({
            "limits": {"files": MAX_FILES, "file_bytes": MAX_FILE_BYTES,
                       "total_bytes": MAX_TOTAL_BYTES, "items": MAX_ITEMS,
                       "tree_bytes": MAX_TREE_BYTES},
            "files_inventoried": 0, "files_read": 0, "bytes_read": 0,
            "working_tree": "not read; dirty/untracked content excluded",
        })
        raw = _git(root, "ls-tree", "-r", "-z", "-l", material.revision)
        entries: list[tuple[str, str, str, str, int]] = []
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            meta, path_bytes = entry.split(b"\t", 1)
            mode, kind, oid, size = meta.decode("ascii").split()
            path = path_bytes.decode("utf-8", errors="surrogateescape")
            entries.append((path, mode, kind, oid, int(size) if size != "-" else 0))
        bundle.coverage["files_inventoried"] = len(entries)
        for path, mode, kind, oid, size in sorted(entries):
            evidence = self._evidence(material, path, oid, "git-tree", None)
            reason = self._excluded(path)
            if mode not in ("100644", "100755") or kind != "blob":
                reason = "symlink, submodule or non-regular tree entry; not followed"
            if reason:
                bundle.coverage["exclusions"].append({"evidence": evidence, "reason": reason})
                continue
            extractor = self._extractor(path)
            if extractor is None:
                bundle.residue["not_targeted"].append({
                    "evidence": evidence, "kind": "unsupported-file", "count": 1,
                    "summary": "File type outside current extraction; content not read",
                })
                continue
            if size > MAX_FILE_BYTES:
                reason = "file exceeds byte limit"
            elif bundle.coverage["files_read"] >= MAX_FILES:
                reason = "file count limit reached"
            elif bundle.coverage["bytes_read"] + size > MAX_TOTAL_BYTES:
                reason = "total byte limit reached"
            elif len(bundle.items) >= MAX_ITEMS:
                reason = "item limit reached; file not read"
            if reason:
                bundle.coverage["gaps"].append({"evidence": evidence, "reason": reason})
                continue
            bundle.coverage["files_read"] += 1
            try:
                source_bytes = _git(root, "cat-file", "blob", oid, maximum=MAX_FILE_BYTES)
                bundle.coverage["bytes_read"] += len(source_bytes)
                source = source_bytes.decode("utf-8-sig")
                if SECRET_RE.search(source):
                    bundle.coverage["exclusions"].append({
                        "evidence": evidence, "reason": "recognized credential pattern; content not extracted",
                    })
                    continue
                self._extract(bundle, source, path, oid, extractor)
            except (MetabolizerError, UnicodeError, SyntaxError, ValueError, TypeError) as exc:
                bundle.coverage["errors"].append({
                    "evidence": evidence, "extractor": extractor,
                    "reason": redact_secrets(str(exc))[:1000],
                })
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in bundle.items:
            groups[("items", item["kind"], item["title"].casefold())].append(item["evidence"])
        for remainder in bundle.residue["not_targeted"]:
            groups[("not_targeted", remainder["kind"], remainder["summary"].casefold())].append(remainder["evidence"])
        bundle.residue["frequency"] = [
            {"section": section, "kind": kind, "title": title, "count": len(evidence), "evidence": evidence}
            for (section, kind, title), evidence in sorted(groups.items()) if len(evidence) > 1
        ]
        return bundle

    def _excluded(self, path: str) -> str:
        parts = PurePosixPath(path).parts
        name = parts[-1].lower()
        if any(part in EXCLUDED_DIRS for part in parts[:-1]):
            return "generated/cache/vendor directory"
        if name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key", ".p12", ".pfx")) \
                or name in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"}:
            return "sensitive filename"
        if any(fnmatchcase(path, pattern) for pattern in self.exclusions):
            return "registered exclusion"
        return ""

    @staticmethod
    def _extractor(path: str) -> str | None:
        name = PurePosixPath(path).name
        if path.endswith(".py"):
            return "python-ast"
        if name in {"package.json", "composer.json"}:
            return "json-manifest"
        if name.startswith("requirements") and name.endswith(".txt"):
            return "requirements"
        if path.lower().endswith(".md"):
            return "markdown-headings"
        return None

    @staticmethod
    def _evidence(material: MaterialReference, path: str, oid: str,
                  extractor: str, line: int | None) -> dict[str, Any]:
        return {"identity": material.identity, "revision": material.revision,
                "path": redact_secrets(path), "blob": oid, "line": line,
                "extractor": extractor, "extractor_version": "1"}

    def _extract(self, bundle: Digestion, source: str, path: str, oid: str, extractor: str) -> None:
        def evidence(line: int | None = None) -> dict[str, Any]:
            return self._evidence(bundle.material, path, oid, extractor, line)

        def add(kind: str, title: str, summary: str, line: int | None = None) -> None:
            ev = evidence(line)
            if len(bundle.items) >= MAX_ITEMS:
                bundle.coverage["gaps"].append({"evidence": ev, "reason": "item limit reached within file"})
                return
            digest = hashlib.sha256(json.dumps([ev, kind, title, summary], sort_keys=True).encode("utf-8")).hexdigest()
            bundle.items.append({"id": f"ITEM-{digest[:24]}", "kind": kind, "title": redact_secrets(title)[:240],
                                 "summary": redact_secrets(summary)[:240], "evidence": ev,
                                 "status": "provisional", "dispositions": list(DISPOSITIONS)})

        def remainder(kind: str, summary: str, count: int, line: int | None = None) -> None:
            bundle.residue["not_targeted"].append({
                "kind": kind, "summary": redact_secrets(summary)[:240],
                "count": count, "evidence": evidence(line),
            })

        if extractor == "python-ast":
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("_"):
                        remainder("private-symbol", node.name, 1, node.lineno)
                    else:
                        doc = ast.get_docstring(node) or ""
                        add("python-symbol", node.name, doc.splitlines()[0] if doc else type(node).__name__, node.lineno)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names]
                    remainder("import", " ".join(([node.module] if isinstance(node, ast.ImportFrom) and node.module else []) + names),
                              len(names), node.lineno)
            unexamined = sum(not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                                                   ast.Import, ast.ImportFrom)) for node in tree.body)
            if unexamined:
                remainder("other-python-statements", "Top-level statements outside symbol/import extraction", unexamined)
            remainder("python-implementation", "Function/class bodies and nested symbols not analyzed", 1)
        elif extractor == "json-manifest":
            data = json.loads(source, object_pairs_hook=_json_object)
            if not isinstance(data, dict):
                raise ValueError("manifest must be a JSON object")
            dependency_fields = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies") \
                if PurePosixPath(path).name == "package.json" else ("require", "require-dev")
            if "name" in data and not isinstance(data["name"], str):
                raise ValueError("manifest name must be a string")
            for field in dependency_fields:
                dependencies = data.get(field, {})
                if not isinstance(dependencies, dict) or any(not isinstance(v, str) for v in dependencies.values()):
                    raise ValueError(f"{field} must map dependency names to string versions")
            if data.get("name"):
                add("package", data["name"], "Declared package name")
            for field in dependency_fields:
                for name, version in sorted(data.get(field, {}).items()):
                    add("dependency", name, f"{field}: {version}")
            other = sorted(set(data) - {"name", *dependency_fields})
            if other:
                remainder("manifest-fields", "Fields not targeted: " + ", ".join(other), len(other))
        elif extractor == "requirements":
            for number, line in enumerate(source.splitlines(), 1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9,._-]+\])?\s*((?:[<>=!~].*)?)", text)
                if match and not any(token in text for token in ("http:", "https:", "git+", " @ ")):
                    add("dependency", match[1], text, number)
                else:
                    remainder("requirements-directive", "Unparsed requirement/directive; not resolved or fetched", 1, number)
        else:
            headings = 0
            fence: str | None = None
            for number, line in enumerate(source.splitlines(), 1):
                stripped = line.lstrip()
                marker = re.match(r"(`{3,}|~{3,})", stripped)
                if marker:
                    if fence is None:
                        fence = marker[1][0]
                    elif marker[1][0] == fence:
                        fence = None
                    continue
                if fence:
                    continue
                match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
                if match:
                    headings += 1
                    add("documentation-topic", match[1], "Markdown heading, not an inferred decision", number)
            remainder("documentation-body", "Body/frontmatter/setext headings not targeted; no decision inference", 1)
            if not headings:
                remainder("unheaded-document", "Document has no targeted headings", 1)


class RepositoryMetabolizer:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR, factory_root: Path = FACTORY_ROOT) -> None:
        self.data_dir = data_dir.resolve()
        self.factory_root = factory_root.resolve()
        self._safe_storage(PROJECT_ROOT.resolve(), self.factory_root)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "repo_metabolizer.sqlite"
        with closing(self._connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS repositories (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, identity TEXT NOT NULL,
                    revision TEXT NOT NULL, exclusions TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, bundle TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL,
                    item_id TEXT NOT NULL, action TEXT NOT NULL, note TEXT NOT NULL, reviewed_at TEXT NOT NULL);
            """)

    def _connect(self) -> sqlite3.Connection:
        self._safe_storage(PROJECT_ROOT.resolve(), self.factory_root)
        if self.db_path.resolve() != self.db_path:
            raise MetabolizerError("metabolizer database must not be a linked file")
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _safe_storage(self, *sources: Path) -> None:
        for source in sources:
            if self.data_dir == source or source in self.data_dir.parents:
                raise MetabolizerError("metabolizer data directory must be outside source repositories")
        for ancestor in (self.data_dir, *self.data_dir.parents):
            if (ancestor / ".git").exists():
                raise MetabolizerError("metabolizer data directory must be outside Git repositories")

    def register(self, repo_id: str, path: Path, identity: str, revision: str = "HEAD",
                 exclusions: list[str] | None = None) -> dict[str, Any]:
        repo_id = _text(repo_id, "repository id", 100)
        identity = _text(identity, "repository identity")
        revision = _text(revision, "revision")
        root = _repo_root(path)
        self._safe_storage(root)
        _revision(root, revision)
        patterns = exclusions if exclusions is not None else []
        if not isinstance(patterns, list) or len(patterns) > 50:
            raise MetabolizerError("exclusions must be a list of at most 50 path globs")
        patterns = [_text(pattern, "exclusion") for pattern in patterns]
        with closing(self._connect()) as conn:
            try:
                conn.execute("INSERT INTO repositories VALUES (?, ?, ?, ?, ?)",
                             (repo_id, str(root), identity, revision, json.dumps(patterns)))
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise MetabolizerError("repository id or path already registered; unregister explicitly first") from exc
        return {"id": repo_id, "path": str(root), "identity": identity, "revision": revision,
                "exclusions": patterns, "scan_started": False}

    def repositories(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM repositories ORDER BY id").fetchall()
        return [{**dict(row), "exclusions": json.loads(row["exclusions"])} for row in rows]

    def unregister(self, repo_id: str) -> dict[str, Any]:
        repo_id = _text(repo_id, "repository id", 100)
        with closing(self._connect()) as conn:
            deleted = conn.execute("DELETE FROM repositories WHERE id=?", (repo_id,))
            if not deleted.rowcount:
                raise MetabolizerError("repository is not registered")
            conn.commit()
        return {"id": repo_id, "eligible": False, "past_scans": "retained for human review"}

    def scan(self, repo_id: str, revision: str | None = None) -> dict[str, Any]:
        repo_id = _text(repo_id, "repository id", 100)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM repositories WHERE id=?", (repo_id,)).fetchone()
        if row is None:
            raise MetabolizerError("repository is not registered; no scan performed")
        root = _repo_root(Path(row["path"]))
        self._safe_storage(root)
        commit = _revision(root, revision if revision is not None else row["revision"])
        material = MaterialReference("repository", row["identity"], commit, str(root))
        bundle = RepositoryDigester(json.loads(row["exclusions"])).digest(material).to_dict()
        self._compare(bundle)
        scan_id = f"DIGEST-{uuid.uuid4()}"
        bundle.update({"scan_id": scan_id, "scanned_at": datetime.now(timezone.utc).isoformat(),
                       "registration": {**dict(row), "exclusions": json.loads(row["exclusions"])}})
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO scans VALUES (?, ?, ?)", (scan_id, repo_id, json.dumps(bundle, sort_keys=True)))
            conn.commit()
        return {**bundle, "reviews": []}

    def get(self, scan_id: str) -> dict[str, Any]:
        scan_id = _text(scan_id, "scan id", 100)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT bundle FROM scans WHERE id=?", (scan_id,)).fetchone()
            if row is None:
                raise MetabolizerError("scan not found")
            reviews = conn.execute(
                "SELECT item_id, action, note, reviewed_at FROM reviews WHERE scan_id=? ORDER BY sequence",
                (scan_id,),
            ).fetchall()
        return {**json.loads(row["bundle"]), "reviews": [dict(r) for r in reviews]}

    def review(self, scan_id: str, item_id: str, action: str, note: str = "") -> dict[str, Any]:
        scan_id = _text(scan_id, "scan id", 100)
        item_id = _text(item_id, "item id", 100)
        if action not in REVIEW_ACTIONS:
            raise MetabolizerError("unsupported human review action")
        if not isinstance(note, str) or len(note) > 2000 or SECRET_RE.search(note):
            raise MetabolizerError("note must be at most 2000 characters without recognized credentials")
        bundle = self.get(scan_id)
        if item_id not in {item["id"] for item in bundle["items"]}:
            raise MetabolizerError("item not found in scan")
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO reviews (scan_id,item_id,action,note,reviewed_at) VALUES (?, ?, ?, ?, ?)",
                         (scan_id, item_id, action, note, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        return self.get(scan_id)

    def _compare(self, bundle: dict[str, Any]) -> None:
        inventory: dict[str, Any] = {
            "gaps": [
                "Product-library graph discovery is not implemented; only configured incubator registries, "
                "DNCP modules and an available matching-root Fabric cache are compared.",
                "Missing matches do not prove novelty. Relevance does not establish suitability or trust.",
                "No sibling repository scans, external research, cache rebuild or conversation harvesting.",
                "DNCP module summaries cover public top-level symbols only; at most eight functions per module. "
                "Capability/FTS matches are bounded by their existing search limits and 20 displayed matches per item.",
            ], "errors": [], "registries": [], "dncp_modules": [],
        }
        for name in ("skill", "runbook"):
            path = self.factory_root / "cockpit" / f"{name}-registry.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("entries"), list) \
                        or any(not isinstance(e, dict) or not isinstance(e.get("id"), str)
                               or not isinstance(e.get("title"), str) or not isinstance(e.get("path", ""), str)
                               or any(not isinstance(e.get(field, []), list)
                                      or any(not isinstance(ref, str) for ref in e.get(field, []))
                                      for field in ("upstream_refs", "downstream_refs"))
                               for e in data["entries"]):
                    raise ValueError("registry requires string id/title/path and string-array provenance refs")
                inventory["registries"].append({"path": str(path), "status": "read-current"})
            except (OSError, ValueError, TypeError) as exc:
                inventory["errors"].append({"path": str(path), "reason": str(exc)})
        if not (self.factory_root / "knowledge" / "patterns").is_dir():
            inventory["gaps"].append("Incubator pattern directory unavailable")
        modules: list[dict[str, Any]] = []
        module_root = PROJECT_ROOT / "control_plane"
        if not module_root.is_dir():
            inventory["gaps"].append("DNCP module directory unavailable")
        for path in sorted(module_root.glob("*.py")):
            try:
                if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
                    inventory["gaps"].append(f"DNCP module skipped (link or size): {path}")
                    continue
                doc, symbols = _module_details(path.read_text(encoding="utf-8"))
                modules.append({"id": f"MOD:devnet-control-plane:{path.name}", "title": path.stem,
                                "summary": doc, "symbols": symbols, "path": str(path),
                                "status": "unverified", "kind": "dncp-module"})
                inventory["dncp_modules"].append(str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                inventory["errors"].append({"path": str(path), "reason": str(exc)})
        fabric_path = self.data_dir / "control_plane_fabric.sqlite"
        if fabric_path.resolve() != fabric_path:
            raise MetabolizerError("Fabric database must not be a linked file")
        fabric = FabricIndex(fabric_path, self.factory_root)
        usable_fabric: FabricIndex | None = None
        try:
            inventory["fabric"] = fabric.freshness()
            if inventory["fabric"]["built"] and inventory["fabric"]["factory_root"] == str(self.factory_root):
                usable_fabric = fabric
                if not inventory["fabric"]["rebuilt_at"]:
                    inventory["gaps"].append("Fabric freshness is unknown")
                inventory["gaps"].append("Fabric is cached; current source revision and completeness are unverified")
            else:
                inventory["gaps"].append("Fabric unavailable or belongs to another root; no implicit rebuild")
        except (OSError, ValueError, sqlite3.Error) as exc:
            inventory["errors"].append({"source": "Fabric", "reason": str(exc)})
        for item in bundle["items"]:
            tokens = [t for t in re.findall(r"[A-Za-z0-9_]+", item["title"]) if len(t) >= 2][:12]
            query = " ".join(tokens)
            matches: list[dict[str, Any]] = []
            if query:
                try:
                    caps = discover_capabilities(query, self.factory_root, usable_fabric, include_modules=False)
                    for group in ("existing_tools_and_modules", "related_patterns", "have_we_solved_this_before"):
                        for match in caps[group]:
                            if match.get("kind") == "conversation":
                                continue
                            source = match.get("abs_path") or (
                                str(self.factory_root / match["path"]) if match.get("path") else ""
                            )
                            matches.append({
                                "id": match["id"], "title": redact_secrets(match["title"])[:240],
                                "status": match.get("status", "unverified"),
                                "evidence": {"path": source, "source_available": bool(source and Path(source).is_file()),
                                             "upstream_refs": match.get("upstream_refs", [])},
                                "rationale": "Existing capability discovery text/FTS relevance; unverified fit",
                            })
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                    inventory["errors"].append({"query": query, "reason": str(exc)})
                for module in modules:
                    text = f"{module['title']} {module['summary']} {' '.join(module['symbols'])}".lower()
                    terms = [t for t in tokens if t.lower() in text]
                    if terms:
                        matches.append({
                            "id": module["id"], "title": module["title"], "status": "unverified",
                            "evidence": {"path": module["path"], "source_available": True},
                            "rationale": "DNCP module text/symbol overlap: " + ", ".join(terms),
                        })
            item["comparison"] = {
                "query": query, "matches": matches[:20], "total_matches": len(matches),
                "notice": "Missing match does not prove novelty; matches are not trust or approval.",
            }
        bundle["inventory"] = inventory
