"""Real-Git isolated digestion contracts; no external repositories or services."""

from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import release

from control_plane.cli import main
from control_plane.digester import DISPOSITIONS, REVIEW_ACTIONS, MaterialReference
from control_plane.fabric import FabricIndex
from control_plane.repo_metabolizer import (
    MAX_FILE_BYTES, MetabolizerError, RepositoryDigester, RepositoryMetabolizer,
)


class TestRepositoryMetabolizer(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.factory = self.root / "incubator"
        self.factory.mkdir()
        self.data = self.root / "runtime"
        self.git("init", "-q")
        self.git("config", "user.name", "Digester Test")
        self.git("config", "user.email", "digester@example.invalid")
        self.write("a.py", '"""sqlite library"""\nimport sqlite3\n'
                   'def search_sqlite():\n    """Search SQLite evidence."""\n    pass\n'
                   'def _hidden(): pass\n')
        self.write("b.py", "import sqlite3\nasync def search_sqlite(): pass\n")
        self.write("README.md", "# SQLite search\n\n```python\n# Not a topic\n```\n## Evidence\n")
        self.write("notes.md", "Not targeted but retained as remainder.\n")
        self.write("requirements.txt", "sqlite-utils==3.0\n-r more.txt\n")
        self.write("package.json", json.dumps({
            "name": "sqlite-tool", "dependencies": {"sqlite-utils": "^3"},
            "devDependencies": {"sqlite-utils": "^3"}, "scripts": {"test": "never run"},
        }))
        self.write("unknown.rs", "fn search() {}")
        self.write("ignored/extra.py", "def excluded(): pass")
        self.write("node_modules/bad.py", "def never_read(): pass")
        self.write(".env", "PRIVATE=never extracted")
        self.commit = self.commit_all()
        self.service = RepositoryMetabolizer(self.data, self.factory)
        cockpit = self.factory / "cockpit"
        cockpit.mkdir()
        for kind in ("skill", "runbook"):
            (cockpit / f"{kind}-registry.json").write_text(json.dumps({
                "entries": [{"id": "SKL-9999", "title": "SQLite search", "path": "tools.md",
                             "status": "provisional"}] if kind == "skill" else [],
            }), encoding="utf-8")
        (self.factory / "tools.md").write_text("SQLite tool", encoding="utf-8")
        folder = self.factory / "knowledge" / "patterns"
        folder.mkdir(parents=True)
        (folder / "PAT-9999.md").write_text(
            '---\nid: "PAT-9999"\ntitle: "SQLite search"\ntype: "pattern"\n'
            'status: "draft"\nupstream_refs: [SRC-9999]\n---\nSQLite search reuse', encoding="utf-8",
        )

    def git(self, *args: str) -> bytes:
        result = subprocess.run(["git", "--no-pager", "-C", str(self.repo), *args],
                                capture_output=True, check=True, input=b"" if "--stdin" in args else None)
        return result.stdout

    def write(self, path: str, source: str) -> None:
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")

    def commit_all(self) -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", "Fixture")
        return self.git("rev-parse", "HEAD").decode().strip()

    def register(self) -> None:
        self.service.register("fixture", self.repo, "test/fixture", exclusions=["ignored/*"])

    def material(self, commit: str | None = None) -> MaterialReference:
        return MaterialReference("repository", "test/fixture", commit or self.commit, str(self.repo))

    def snapshot(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}

    def test_opt_in_registration_does_not_scan_and_no_phone_home_dependency(self) -> None:
        with patch("control_plane.repo_metabolizer._git", side_effect=AssertionError("source read")):
            with self.assertRaisesRegex(MetabolizerError, "not registered"):
                self.service.scan("fixture")
        with patch.object(RepositoryDigester, "digest", side_effect=AssertionError("automatic scan")):
            self.register()
        self.assertEqual(len(self.service.repositories()), 1)
        self.assertFalse((self.data / "phone_home.sqlite").exists())
        self.assertFalse((self.data / "control_plane_fabric.sqlite").exists())
        with self.assertRaisesRegex(MetabolizerError, "already registered"):
            self.register()
        self.service.unregister("fixture")
        self.assertEqual(self.service.repositories(), [])
        with self.assertRaises(MetabolizerError):
            self.service.scan("fixture")

    def test_committed_revision_read_only_and_deterministic(self) -> None:
        self.register()
        self.write("a.py", "def dirty_only(): pass\n")
        self.write("untracked.py", "def untracked_only(): pass\n")
        status = self.git("status", "--porcelain=v1")
        before = self.snapshot()
        first = RepositoryDigester(["ignored/*"]).digest(self.material()).to_dict()
        second = RepositoryDigester(["ignored/*"]).digest(self.material()).to_dict()
        self.assertEqual(first, second)
        scan = self.service.scan("fixture")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(status, self.git("status", "--porcelain=v1"))
        self.assertEqual(scan["material"]["revision"], self.commit)
        names = {item["title"] for item in scan["items"]}
        self.assertIn("search_sqlite", names)
        self.assertNotIn("dirty_only", names)
        self.assertNotIn("untracked_only", names)
        self.assertNotIn("Not a topic", names)
        self.assertNotIn("excluded", names)
        self.assertEqual(scan["coverage"]["files_inventoried"], 10)
        self.assertEqual(scan["coverage"]["files_read"], 6)
        self.assertEqual(scan["coverage"]["errors"], [])
        exclusions = {entry["evidence"]["path"]: entry["reason"] for entry in scan["coverage"]["exclusions"]}
        self.assertEqual(exclusions["ignored/extra.py"], "registered exclusion")
        self.assertEqual(exclusions[".env"], "sensitive filename")
        self.assertIn("node_modules/bad.py", exclusions)
        for item in scan["items"]:
            self.assertEqual(item["status"], "provisional")
            self.assertEqual(item["dispositions"], list(DISPOSITIONS))
            ev = item["evidence"]
            self.assertEqual(ev["revision"], self.commit)
            self.assertEqual(ev["identity"], "test/fixture")
            self.assertEqual(len(ev["blob"]), 40)
            self.assertEqual(ev["extractor_version"], "1")
        self.assertEqual(len({item["id"] for item in scan["items"]}), len(scan["items"]))
        updated_commit = self.commit_all()
        old = self.service.scan("fixture", self.commit)
        new = self.service.scan("fixture", updated_commit)
        self.assertIn("search_sqlite", {item["title"] for item in old["items"]})
        self.assertIn("dirty_only", {item["title"] for item in new["items"]})
        with self.assertRaises(MetabolizerError):
            self.service.scan("fixture", "--output=/not-allowed")

    def test_residue_and_frequency_are_preserved_not_deduplicated(self) -> None:
        bundle = RepositoryDigester(["ignored/*"]).digest(self.material()).to_dict()
        residues = bundle["residue"]["not_targeted"]
        self.assertTrue(any(r["kind"] == "unsupported-file" and r["evidence"]["path"] == "unknown.rs" for r in residues))
        self.assertTrue(any(r["kind"] == "private-symbol" and r["summary"] == "_hidden" for r in residues))
        self.assertTrue(any(r["kind"] == "unheaded-document" and r["evidence"]["path"] == "notes.md" for r in residues))
        self.assertTrue(any(r["kind"] == "manifest-fields" and "scripts" in r["summary"] for r in residues))
        self.assertTrue(any(r["kind"] == "requirements-directive" for r in residues))
        self.assertEqual(len([i for i in bundle["items"] if i["title"] == "search_sqlite"]), 2)
        frequencies = bundle["residue"]["frequency"]
        repeated = next(f for f in frequencies if f["title"] == "search_sqlite")
        self.assertEqual(repeated["count"], 2)
        self.assertEqual(len(repeated["evidence"]), 2)
        dependency = next(f for f in frequencies if f["kind"] == "dependency" and f["title"] == "sqlite-utils")
        self.assertEqual(dependency["count"], 3)
        imports = next(f for f in frequencies if f["section"] == "not_targeted" and f["kind"] == "import")
        self.assertEqual(imports["count"], 2)

    def test_inventory_cites_existing_evidence_and_fabric_without_rebuild(self) -> None:
        self.register()
        fabric = FabricIndex(self.data / "control_plane_fabric.sqlite", self.factory)
        fabric.rebuild(include_conversations=False)
        with patch.object(FabricIndex, "rebuild", side_effect=AssertionError("implicit rebuild")), \
             patch("control_plane.phone_home.PhoneHome", side_effect=AssertionError("phone home")), \
             patch("control_plane.capabilities.scan_network_modules", side_effect=AssertionError("sibling scan")):
            scan = self.service.scan("fixture")
        topics = next(i for i in scan["items"] if i["title"] == "SQLite search")
        matches = topics["comparison"]["matches"]
        ids = {match["id"] for match in matches}
        self.assertIn("SKL-9999", ids)
        self.assertIn("PAT-9999", ids)
        self.assertTrue(any(match["id"].startswith("MOD:devnet-control-plane:") for match in matches))
        skill = next(match for match in matches if match["id"] == "SKL-9999")
        self.assertEqual(skill["evidence"]["path"], str(self.factory / "tools.md"))
        self.assertEqual(skill["status"], "provisional")
        self.assertIn("unverified", skill["rationale"])
        self.assertFalse(scan["inventory"]["fabric"]["includes_conversations"])
        self.assertTrue(scan["inventory"]["fabric"]["rebuilt_at"])
        self.assertTrue(any("graph" in gap for gap in scan["inventory"]["gaps"]))
        self.assertIn("novelty", scan["notice"])
        (self.factory / "cockpit" / "skill-registry.json").write_text("{invalid", encoding="utf-8")
        scan = self.service.scan("fixture")
        self.assertTrue(any("skill-registry" in e.get("path", "") for e in scan["inventory"]["errors"]))

    def test_missing_or_wrong_root_inventory_is_not_false_novelty(self) -> None:
        self.register()
        missing = RepositoryMetabolizer(self.data, self.root / "missing")
        scan = missing.scan("fixture")
        self.assertEqual(len(scan["inventory"]["errors"]), 2)
        self.assertFalse(scan["inventory"]["fabric"]["built"])
        self.assertTrue(any("no implicit rebuild" in gap for gap in scan["inventory"]["gaps"]))
        other = self.root / "other-factory"
        other.mkdir()
        FabricIndex(self.data / "control_plane_fabric.sqlite", other).rebuild(include_conversations=False)
        with patch.object(FabricIndex, "rebuild", side_effect=AssertionError("root switch")):
            scan = self.service.scan("fixture")
        self.assertEqual(scan["inventory"]["fabric"]["factory_root"], str(other))
        self.assertTrue(any("another root" in gap for gap in scan["inventory"]["gaps"]))

    def test_bounded_extraction_errors_and_explicit_omissions(self) -> None:
        self.write("too_big.py", "x" * (MAX_FILE_BYTES + 1))
        self.write("invalid.py", "def invalid(")
        self.write("bad/package.json", '{"dependencies": []}')
        self.write("duplicate/package.json", '{"name":"a","name":"b"}')
        self.write("credential.py", '# ghp_' + "a" * 30 + "\ndef should_not_leak(): pass")
        (self.repo / "binary.py").write_bytes(b"\xff\xfe")
        commit = self.commit_all()
        bundle = RepositoryDigester().digest(self.material(commit)).to_dict()
        errors = {e["evidence"]["path"]: e["reason"] for e in bundle["coverage"]["errors"]}
        self.assertIn("invalid.py", errors)
        self.assertIn("binary.py", errors)
        self.assertIn("bad/package.json", errors)
        self.assertIn("duplicate", errors["duplicate/package.json"])
        self.assertTrue(any(e["evidence"]["path"] == "too_big.py" for e in bundle["coverage"]["gaps"]))
        self.assertTrue(any(e["evidence"]["path"] == "credential.py" for e in bundle["coverage"]["exclusions"]))
        self.assertNotIn("ghp_" + "a" * 30, json.dumps(bundle))
        with patch("control_plane.repo_metabolizer.MAX_ITEMS", 1):
            bounded = RepositoryDigester().digest(self.material()).to_dict()
        self.assertEqual(len(bounded["items"]), 1)
        self.assertTrue(any("item limit" in e["reason"] for e in bounded["coverage"]["gaps"]))
        with patch("control_plane.repo_metabolizer.MAX_FILES", 1):
            bounded = RepositoryDigester().digest(self.material()).to_dict()
        self.assertEqual(bounded["coverage"]["files_read"], 1)
        self.assertTrue(any("file count" in e["reason"] for e in bounded["coverage"]["gaps"]))
        with patch("control_plane.repo_metabolizer.MAX_TOTAL_BYTES", 1):
            bounded = RepositoryDigester().digest(self.material()).to_dict()
        self.assertEqual(bounded["coverage"]["bytes_read"], 0)
        self.assertTrue(any("total byte" in e["reason"] for e in bounded["coverage"]["gaps"]))

    def test_tree_output_bound_fails_without_persisting_partial_success(self) -> None:
        self.register()
        real_git = subprocess.run

        def excessive_output(command, **kwargs):
            if "ls-tree" in command:
                kwargs["stdout"].write(b"x" * (4 * 1024 * 1024 + 1))
                return subprocess.CompletedProcess(command, 0, stderr=b"")
            return real_git(command, **kwargs)

        with patch("control_plane.repo_metabolizer.subprocess.run", side_effect=excessive_output):
            with self.assertRaisesRegex(MetabolizerError, "exceeds"):
                self.service.scan("fixture")
        with closing(self.service._connect()) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM scans").fetchone()[0], 0)

    def test_link_and_submodule_entries_never_followed(self) -> None:
        target = self.root / "outside.py"
        target.write_text("def outside(): pass", encoding="utf-8")
        blob = self.git("hash-object", "-w", "--stdin")  # empty link target is still never followed
        self.git("update-index", "--add", "--cacheinfo", "120000", blob.decode().strip(), "linked.py")
        self.git("update-index", "--add", "--cacheinfo", "160000", self.commit, "submodule")
        self.git("commit", "-qm", "Tree links")
        revision = self.git("rev-parse", "HEAD").decode().strip()
        scan = RepositoryDigester().digest(self.material(revision)).to_dict()
        exclusions = {e["evidence"]["path"]: e["reason"] for e in scan["coverage"]["exclusions"]}
        self.assertIn("symlink", exclusions["linked.py"])
        self.assertIn("submodule", exclusions["submodule"])
        self.assertNotIn("outside", {item["title"] for item in scan["items"]})
        self.assertEqual(target.read_text(encoding="utf-8"), "def outside(): pass")

    def test_storage_and_registration_boundaries(self) -> None:
        with self.assertRaisesRegex(MetabolizerError, "outside"):
            RepositoryMetabolizer(self.repo / "runtime", self.factory)
        with self.assertRaisesRegex(MetabolizerError, "outside"):
            RepositoryMetabolizer(self.factory / "runtime", self.factory)
        with self.assertRaisesRegex(MetabolizerError, "top-level"):
            self.service.register("subdir", self.repo / "ignored", "test/subdir")
        with self.assertRaises(MetabolizerError):
            self.service.register("missing", self.root / "missing", "test/missing")
        with self.assertRaises(MetabolizerError):
            self.service.register("bad-ref", self.repo, "test/fixture", "unresolvablezzzz")
        with self.assertRaises(MetabolizerError):
            self.service.register("bad-globs", self.repo, "test/fixture", exclusions={})
        # A runtime directory created before its containing source becomes a repo is also refused.
        outer = self.root / "later-repo"
        outer.mkdir()
        service = RepositoryMetabolizer(outer / "runtime", self.factory)
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        with self.assertRaisesRegex(MetabolizerError, "outside"):
            service.register("later", outer, "test/later")

    def test_human_dispositions_append_durably_without_promotion(self) -> None:
        self.register()
        bundle = self.service.scan("fixture")
        before = self.snapshot()
        scan_id = bundle["scan_id"]
        item_id = bundle["items"][0]["id"]
        for action in REVIEW_ACTIONS:
            reviewed = self.service.review(scan_id, item_id, action, "Human evaluation")
        reopened = RepositoryMetabolizer(self.data, self.factory)
        self.assertEqual([r["action"] for r in reopened.get(scan_id)["reviews"]], list(REVIEW_ACTIONS))
        normalized = self.service.review(f" {scan_id} ", f" {item_id} ", "defer")
        self.assertEqual(len(normalized["reviews"]), len(REVIEW_ACTIONS) + 1)
        self.assertTrue(all(i["status"] == "provisional" for i in reviewed["items"]))
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(MetabolizerError):
            self.service.review(scan_id, "missing", DISPOSITIONS[0])
        with self.assertRaises(MetabolizerError):
            self.service.review(scan_id, item_id, "auto-promote")
        self.service.unregister("fixture")
        self.assertEqual(reopened.get(scan_id)["scan_id"], scan_id)

    def test_cli_all_operations_without_phone_home(self) -> None:
        base = ["--factory-root", str(self.factory), "--data-dir", str(self.data), "metabolizer"]

        def call(*args: str, expected: int = 0):
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error), \
                 patch("control_plane.cli.PhoneHome", side_effect=AssertionError("dependency")):
                code = main([*base, *args])
            self.assertEqual(code, expected, error.getvalue())
            return json.loads(output.getvalue() if expected == 0 else error.getvalue())

        self.assertFalse(call("register", "cli-fixture", str(self.repo), "--identity", "test/fixture")["scan_started"])
        self.assertEqual(len(call("list")), 1)
        bundle = call("scan", "cli-fixture", "--revision", self.commit)
        self.assertEqual(call("get", bundle["scan_id"]), bundle)
        reviewed = call("review", bundle["scan_id"], bundle["items"][0]["id"],
                        "--action", DISPOSITIONS[0], "--note", "Reviewed locally")
        self.assertEqual(reviewed["reviews"][0]["action"], DISPOSITIONS[0])
        self.assertFalse(call("unregister", "cli-fixture")["eligible"])
        self.assertIn("not registered", call("scan", "cli-fixture", expected=1)["error"])
        self.assertFalse((self.data / "phone_home.sqlite").exists())

    def test_git_environment_cannot_redirect_registered_material(self) -> None:
        self.register()
        with patch.dict(os.environ, {"GIT_DIR": str(self.root / "nonexistent")}):
            scan = self.service.scan("fixture")
        self.assertEqual(scan["material"]["revision"], self.commit)

    def test_installed_wheel_digestion_from_unrelated_directory(self) -> None:
        dist = self.root / "dist"
        dist.mkdir()
        wheel = release.build_wheel(dist, release.collect_source_files(release.PROJECT_DIR / "control_plane"))
        target = self.root / "installed"
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--no-index",
             "--target", str(target), str(wheel)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        env = {**os.environ, "PYTHONPATH": str(target)}
        data = self.root / "installed-runtime"

        def invoke(*args: str) -> dict:
            result = subprocess.run(
                [sys.executable, "-m", "control_plane.cli", "--factory-root", str(self.factory),
                 "--data-dir", str(data), "metabolizer", *args],
                cwd=self.root, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

        invoke("register", "installed-fixture", str(self.repo), "--identity", "test/fixture")
        bundle = invoke("scan", "installed-fixture")
        self.assertEqual(bundle["material"]["revision"], self.commit)
        self.assertTrue(any(str(target) in p for p in bundle["inventory"]["dncp_modules"]))
        self.assertEqual(invoke("get", bundle["scan_id"]), bundle)
        self.assertFalse((data / "phone_home.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
