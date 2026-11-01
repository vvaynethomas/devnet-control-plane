"""Opt-in committed-revision digestion, bounded residue and cached comparison safety."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch

from control_plane.cli import main
from control_plane.digester import DigesterError, RepositoryDigester, MAX_FILE_BYTES, MAX_RESIDUE
from control_plane.fabric import FabricIndex


class TestRepositoryDigester(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.data = self.root / "runtime"
        self.git("init", "-q")
        self.write("README.md", "# SQLite reusable adapter\n\nTODO: investigate cache reuse\nTODO: investigate cache reuse\n")
        self.write("tools.py", '"""SQLite reusable adapter."""\nimport sqlite3\nimport sqlite3\n\ndef sqlite_search():\n    raise RuntimeError("never execute repository code")\n')
        self.write("package.json", '{"dependencies":{"fixture-component":"^1.0.0"},"scripts":{"install":"never-run"}}')
        self.write("pyproject.toml", '[project]\nname = "fixture"\ndependencies = ["fixture-component"]\n')
        self.write(".github/workflows/check.yml", "name: static fixture\n# TODO: inspect unrelated workflow\n")
        self.write("unknown.bin", "not recognized")
        self.write(".env", "DO_NOT_READ=private")
        self.write("token.md", "# ghp_" + "a" * 30)
        self.write("node_modules/ignored.py", '"""Excluded."""')
        self.write("huge.md", "x" * (MAX_FILE_BYTES + 1))
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.write("tools.py", "working file private content; MUST NOT READ")
        self.write("untracked.py", "also must not read")
        self.digester = RepositoryDigester(self.data)

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True)
        return result.stdout

    def write(self, relative: str, text: str) -> None:
        path = self.repo / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def snapshot(self) -> dict[str, bytes]:
        return {str(path.relative_to(self.repo)): path.read_bytes() for path in self.repo.rglob("*") if path.is_file()}

    def test_opt_in_and_flag_never_triggers_scan(self) -> None:
        with patch("control_plane.digester._git", side_effect=AssertionError("unregistered repository touched")):
            with self.assertRaisesRegex(DigesterError, "not opted in"):
                self.digester.scan(self.repo)
        before = self.snapshot()
        from control_plane.digester import _git
        with patch("control_plane.digester._git", wraps=_git) as observed:
            receipt = self.digester.register(self.repo)
            self.assertEqual([call.args[1] for call in observed.call_args_list], ["rev-parse"])
        self.assertFalse(receipt["scan_performed"])
        self.assertEqual(before, self.snapshot())
        self.digester.disable(self.repo)
        with self.assertRaisesRegex(DigesterError, "not opted in"):
            self.digester.scan(self.repo)
        self.assertFalse(self.digester.registrations()["repositories"][0]["enabled"])

    def test_useful_static_bundle_readonly_revision_provenance_and_determinism(self) -> None:
        self.digester.register(self.repo)
        before = self.snapshot()
        result = self.digester.scan(self.repo, "sqlite")
        after = self.digester.scan(self.repo, "sqlite")
        self.assertEqual(result["evidence_digest"], after["evidence_digest"])
        self.assertEqual(result["material"]["revision"], self.revision)
        self.assertEqual(result["material"]["type"], "repository")
        self.assertEqual(before, self.snapshot())  # Includes Git config/index/refs and dirty files.
        symbols = [item for item in result["items"] if item["category"] == "python_symbol"]
        self.assertEqual(symbols[0]["title"], "sqlite_search")
        self.assertEqual(symbols[0]["provenance"]["line"], 5)
        self.assertTrue(symbols[0]["provenance"]["link"].startswith("git:" + self.revision))
        self.assertEqual(len(symbols[0]["provenance"]["sha256"]), 64)
        self.assertIn("dependency_declaration", {item["category"] for item in result["items"]})
        declaration = next(item for item in result["items"] if item["category"] == "dependency_declaration")
        self.assertEqual(declaration["provenance"]["location_precision"], "file")
        self.assertIn("configuration", {item["category"] for item in result["items"]})
        self.assertNotIn("untracked.py", [e["path"] for e in result["file_evidence"]])
        serialized = json.dumps(result)
        self.assertNotIn("DO_NOT_READ", serialized)
        self.assertNotIn("private content", serialized)
        self.assertNotIn("ghp_" + "a" * 30, serialized)
        self.assertFalse(result["review"]["automatic_adoption"])
        self.assertFalse(result["review"]["automatic_phone_home"])
        self.assertFalse(result["comparison"]["inventory"]["available"])
        self.assertIn("defer", result["review"]["options"])
        self.assertIn("reject", result["review"]["options"])

    def test_residue_counts_not_corroboration_and_explicit_omissions(self) -> None:
        self.digester.register(self.repo)
        result = self.digester.scan(self.repo, "sqlite")
        repeated = next(r for r in result["residue"]["items"] if r["observation"] == "TODO: investigate cache reuse")
        self.assertEqual(repeated["count"], 2)
        self.assertIn("not independence", repeated["interpretation"])
        self.assertTrue(any(r["observation"].startswith("Untargeted") for r in result["residue"]["items"]))
        exclusions = result["coverage"]["exclusions"]
        self.assertEqual(exclusions["recognized_secret_content"], 1)
        self.assertEqual(exclusions["file_size_limit"], 1)
        self.assertEqual(exclusions["sensitive_filename"], 1)
        self.assertLessEqual(len(result["residue"]["items"]), MAX_RESIDUE)

    def test_retention_caps_and_malformed_material_are_visible(self) -> None:
        self.write("README.md", "\n".join(f"# Untargeted item {i}\nTODO: consideration {i}" for i in range(150)))
        self.write("invalid.py", "def broken(:\n")
        self.write("nested/package.json", "[" * 2000 + "0" + "]" * 2000)
        self.git("add", "README.md", "invalid.py", "nested/package.json")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "bounded fixture")
        self.digester.register(self.repo)
        result = self.digester.scan(self.repo, "absent")
        self.assertEqual(len(result["items"]), 100)
        self.assertEqual(len(result["residue"]["items"]), MAX_RESIDUE)
        self.assertGreater(result["coverage"]["exclusions"]["material_item_limit"], 0)
        self.assertGreater(result["coverage"]["exclusions"]["residue_group_limit"], 0)
        self.assertTrue(any(e["path"] == "invalid.py" for e in result["coverage"]["errors"]))
        self.assertTrue(any(e["path"] == "nested/package.json" for e in result["coverage"]["errors"]))
        self.assertLessEqual(result["comparison"]["inventory"]["items_compared"], 10)

    def test_long_observations_not_falsely_merged_and_git_cannot_lazy_fetch(self) -> None:
        prefix = "TODO: " + "same visible prefix " * 30
        self.write("README.md", prefix + "first tail\n" + prefix + "second tail\n")
        self.git("add", "README.md")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "long observations")
        self.digester.register(self.repo)
        from control_plane.digester import subprocess as observed_subprocess
        original = observed_subprocess.Popen
        with patch("control_plane.digester.subprocess.Popen", wraps=original) as calls:
            result = self.digester.scan(self.repo)
        for call in calls.call_args_list:
            self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(call.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(call.kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
        observations = [r for r in result["residue"]["items"] if r["text_truncated"]]
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0]["observation"], observations[1]["observation"])
        self.assertNotEqual(observations[0]["observation_sha256"], observations[1]["observation_sha256"])
        self.assertEqual([r["count"] for r in observations], [1, 1])
        self.write("README.md", "# " + "t" * 250)
        self.git("add", "README.md")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "title truncation")
        result = self.digester.scan(self.repo)
        heading = next(item for item in result["items"] if item["category"] == "document_heading")
        self.assertTrue(heading["title_truncated"])
        self.assertEqual(result["coverage"]["exclusions"]["material_title_truncation"], 1)

    def test_link_modes_excluded_and_git_environment_cannot_redirect_scan(self) -> None:
        blob = self.git("rev-parse", "HEAD:README.md").strip()
        self.git("update-index", "--add", "--cacheinfo", f"120000,{blob},linked.md")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "link fixture")
        self.digester.register(self.repo)
        with patch.dict("os.environ", {"GIT_DIR": str(self.root / "unregistered.git")}):
            result = self.digester.scan(self.repo)
        self.assertEqual(result["coverage"]["exclusions"]["symlink_submodule_or_nonregular"], 1)
        self.assertNotIn("linked.md", [e["path"] for e in result["file_evidence"]])

    def test_total_content_file_count_and_tree_bounds(self) -> None:
        for index in range(120):
            self.write(f"docs/doc-{index:03}.md", "# bounded file\n")
        self.git("add", "docs")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "file limit")
        self.digester.register(self.repo)
        result = self.digester.scan(self.repo)
        self.assertEqual(result["coverage"]["files_read"], 100)
        self.assertGreater(result["coverage"]["exclusions"]["file_count_limit"], 0)
        with patch("control_plane.digester.MAX_TOTAL_BYTES", 100):
            result = self.digester.scan(self.repo)
        self.assertLessEqual(result["coverage"]["bytes_read"], 100)
        self.assertGreater(result["coverage"]["exclusions"]["total_byte_limit"], 0)
        from control_plane.digester import _git
        with self.assertRaisesRegex(DigesterError, "output exceeded"):
            _git(self.repo, "ls-tree", "-rz", "HEAD", limit=20)

    def test_corrupt_cache_is_reported_without_source_fallback(self) -> None:
        cache = self.data / "bad-cache.sqlite"
        cache.write_bytes(b"not a sqlite database")
        digester = RepositoryDigester(self.data, FabricIndex(cache, self.root / "unregistered"))
        digester.register(self.repo)
        result = digester.scan(self.repo)
        self.assertFalse(result["comparison"]["inventory"]["available"])
        self.assertEqual(result["comparison"]["inventory"]["errors"][0]["error"], "DatabaseError")
        self.assertTrue(result["items"])

    def test_cached_comparison_never_live_scans_or_promotes(self) -> None:
        factory = self.root / "incubator"
        knowledge = factory / "knowledge"
        knowledge.mkdir(parents=True)
        (knowledge / "FND-9876.md").write_text(
            '---\nid: "FND-9876"\ntitle: "SQLite search"\ntype: "finding"\nstatus: "draft"\n'
            'upstream_refs: [SRC-9999]\n---\nSQLite reusable adapter', encoding="utf-8",
        )
        fabric = FabricIndex(self.data / "fabric.sqlite", factory)
        fabric.rebuild(include_conversations=False)
        digester = RepositoryDigester(self.data, fabric)
        digester.register(self.repo)
        with patch.object(fabric, "ensure_built", side_effect=AssertionError("implicit source read")), \
             patch.object(fabric, "rebuild", side_effect=AssertionError("implicit rebuild")):
            result = digester.scan(self.repo, "sqlite")
        comparison = result["comparison"]
        self.assertFalse(comparison["inventory"]["full_product_library_graph"])
        match = next(p for p in comparison["proposals"] if p["matches"])
        self.assertEqual(match["matches"][0]["status"], "draft")
        self.assertEqual(match["status"], "provisional")
        self.assertIn("trust", comparison["inventory"]["unknowns"][-1])
        self.assertFalse((self.data / "phone_home.sqlite").exists())

    def test_cli_registration_and_explicit_scan_without_phone_home(self) -> None:
        args = ["--data-dir", str(self.data), "--factory-root", str(self.root / "missing"), "digest"]
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["scan", str(self.repo)]), 1)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["register", str(self.repo)]), 0)
        self.assertFalse(json.loads(output.getvalue())["scan_performed"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["scan", str(self.repo), "--target", "sqlite"]), 0)
        self.assertEqual(json.loads(output.getvalue())["material"]["revision"], self.revision)
        self.assertFalse((self.data / "phone_home.sqlite").exists())

    def test_installed_wheel_cli_without_source_checkout_or_dependencies(self) -> None:
        import release
        wheel = release.build_release(self.root / "dist")["wheel"]
        environment = self.root / "installed"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", wheel],
                       cwd=self.root, check=True, capture_output=True, timeout=60)
        args = [str(python), "-m", "control_plane.cli", "--data-dir", str(self.data),
                "--factory-root", str(self.root / "missing"), "digest"]
        subprocess.run(args + ["register", str(self.repo)], cwd=self.root, check=True, capture_output=True, timeout=20)
        scan = subprocess.run(args + ["scan", str(self.repo)], cwd=self.root, check=True,
                              capture_output=True, text=True, timeout=30)
        result = json.loads(scan.stdout)
        self.assertEqual(result["material"]["revision"], self.revision)
        self.assertTrue(result["items"])
        self.assertFalse((self.data / "phone_home.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
