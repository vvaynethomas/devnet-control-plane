"""Synthetic coverage for the incremental Fabric index over a PRJ-0006 v1 library."""

from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from control_plane import hub_index
from control_plane.cli import main
from control_plane.conversation_library import APPLICATION_ID, ConversationLibraryError
from control_plane.fabric import FabricIndex
from control_plane.material_capability import MaterialCapabilityError, require_material_core
from control_plane.material_pins import CORE_VERSION

try:
    require_material_core()
    HAS_CORE = True
except MaterialCapabilityError:
    HAS_CORE = False


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(name: str, messages: list[tuple[str, str]], *, revision: str = "r1", title: str | None = None,
           platform: str = "synthetic-cli", updated_at: str = "2026-01-02T00:00:00Z") -> dict:
    return {
        "schema_version": 1, "id": digest(name), "revision": digest(name + revision),
        "created_at": "2026-01-01T00:00:00Z", "updated_at": updated_at, "source_current_node_id": None,
        "source": {"archive_key": "synthetic", "platform": platform, "edition": "v1", "session_id": name,
                   "source_id": None, "source_name": None, "native_session_id": None},
        "provenance": {"producer": "synthetic", "declared_version": "1", "export_uri": f"file:///synthetic/{name}",
                       "export_sha256": digest("export" + name + revision), "pointer": "/0",
                       "observed_at": "2026-01-03T00:00:00Z"},
        "source_record": {"title": title, "padding": "x" * 64},
        "limitations": ["synthetic"],
        "messages": [{"id": digest(f"{name}{revision}{position}"), "position": position, "role": role,
                      "source_role": role, "content": content, "pointer": f"/0/{position}", "timestamp": None,
                      "source_event_id": None, "parent_source_event_id": None, "child_source_event_ids": []}
                     for position, (role, content) in enumerate(messages)],
    }


class HubIndexWithoutCoreTests(unittest.TestCase):
    def test_indexing_without_the_material_extra_fails_before_touching_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fabric = FabricIndex(db_path=root / "data" / "fabric.db", factory_root=root / "factory")
            error = io.StringIO()
            with patch("control_plane.hub_index.require_material_core",
                       side_effect=MaterialCapabilityError("Material capability is not installed.")), \
                    redirect_stdout(io.StringIO()), redirect_stderr(error):
                with self.assertRaises(MaterialCapabilityError):
                    fabric.index_hub(root / "library.sqlite")
            self.assertFalse(fabric.db_path.exists())
            self.assertEqual(fabric.search_hub("anything")["results"], [])


@unittest.skipUnless(HAS_CORE, "Requires the optional pinned material distribution for segmentation")
class HubIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "private # ☃" / "library.sqlite"
        self.library.parent.mkdir()
        with closing(sqlite3.connect(self.library)) as connection:
            connection.executescript(f"""
                PRAGMA application_id = {APPLICATION_ID};
                PRAGMA user_version = 1;
                CREATE TABLE exports (sha256 TEXT PRIMARY KEY, raw BLOB NOT NULL);
                CREATE TABLE revisions (conversation_id TEXT, revision TEXT,
                    PRIMARY KEY (conversation_id, revision));
                CREATE TABLE observations (conversation_id TEXT, revision TEXT,
                    export_sha256 TEXT REFERENCES exports(sha256), export_uri TEXT,
                    normalized_json TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, revision, export_sha256, export_uri),
                    FOREIGN KEY (conversation_id, revision)
                    REFERENCES revisions(conversation_id, revision));
            """)
        self.factory = self.root / "factory"
        self.factory.mkdir()
        self.fabric = FabricIndex(self.root / "data" / "fabric.sqlite", self.factory)

    def add(self, item: dict, *, export_uri: str | None = None) -> None:
        provenance = item["provenance"]
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute("INSERT OR IGNORE INTO exports VALUES (?, ?)", (provenance["export_sha256"], b"raw"))
            connection.execute("INSERT OR IGNORE INTO revisions VALUES (?, ?)", (item["id"], item["revision"]))
            connection.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?)", (
                item["id"], item["revision"], provenance["export_sha256"],
                export_uri or provenance["export_uri"], json.dumps(item, ensure_ascii=False)))

    def remove(self, item: dict) -> None:
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute("DELETE FROM observations WHERE conversation_id = ? AND revision = ?",
                               (item["id"], item["revision"]))
            connection.execute("DELETE FROM revisions WHERE conversation_id = ? AND revision = ?",
                               (item["id"], item["revision"]))

    def search(self, query: str, **kwargs) -> list[dict]:
        return self.fabric.search(query, initialize=False, include_hub=True, **kwargs)["results"]

    def assert_error(self, code: str, library: Path | None = None) -> None:
        with self.assertRaises(ConversationLibraryError) as caught:
            self.fabric.index_hub(library or self.library)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_indexes_searches_and_points_at_the_matching_message(self) -> None:
        first = record("alpha", [("user", "How do we tune the zebrafish pipeline?"),
                                 ("assistant", "Raise the quokka threshold.")], title="Pipeline tuning")
        self.add(first)
        self.add(record("beta", [("user", "Unrelated gardening notes")]))
        result = self.fabric.index_hub(self.library)
        self.assertEqual((result["revisions_added"], result["revisions_removed"]), (2, 0))
        self.assertEqual(result["index"]["conversations"], 2)
        self.assertNotIn("zebrafish", json.dumps(result))
        hits = self.search("quokka")
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual((hit["id"], hit["kind"], hit["harness"]), (f"hub:{first['id']}", "conversation", "synthetic-cli"))
        self.assertEqual((hit["conversation_id"], hit["revision"], hit["revision_count"]),
                         (first["id"], first["revision"], 1))
        self.assertEqual(hit["title"], "Pipeline tuning")
        self.assertIn("<mark>quokka</mark>", hit["snippet"])
        self.assertEqual(self.search("quokka", kind_filter="finding"), [])
        self.assertEqual(self.fabric.search("", initialize=False, include_hub=True)["counts"].get("conversation"), 2)
        default = self.fabric.search("quokka", initialize=False)
        self.assertEqual((default["results"], default["counts"]), ([], {}))

    def test_second_run_only_reads_new_revisions_and_drops_removed_ones(self) -> None:
        kept = record("alpha", [("user", "persistent walrus")])
        gone = record("beta", [("user", "temporary narwhal")])
        self.add(kept)
        self.add(gone)
        self.fabric.index_hub(self.library)
        again = self.fabric.index_hub(self.library)
        self.assertEqual((again["revisions_added"], again["revisions_removed"], again["revisions_unchanged"]), (0, 0, 2))
        self.remove(gone)
        self.add(record("gamma", [("user", "fresh ocelot")]))
        third = self.fabric.index_hub(self.library)
        self.assertEqual((third["revisions_added"], third["revisions_removed"], third["revisions_unchanged"]), (1, 1, 1))
        self.assertEqual(self.search("narwhal"), [])
        self.assertEqual(len(self.search("ocelot")), 1)
        self.assertEqual(len(self.search("walrus")), 1)

    def test_revisions_are_all_kept_and_collapsed_per_conversation(self) -> None:
        self.add(record("alpha", [("user", "capybara plan")], revision="r1", updated_at="2026-01-02T00:00:00Z"))
        self.add(record("alpha", [("user", "capybara plan"), ("assistant", "capybara answer")],
                        revision="r2", updated_at="2026-01-05T00:00:00Z"))
        result = self.fabric.index_hub(self.library)
        self.assertEqual((result["index"]["conversations"], result["index"]["revisions"]), (1, 2))
        hits = self.search("capybara")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["revision_count"], 2)
        browse = self.search("", kind_filter="conversation")
        self.assertEqual([item["message_count"] for item in browse], [2])
        self.fabric.rebuild(include_conversations=False)  # get_entity builds a missing cache; keep it synthetic
        entity = self.fabric.get_entity(hits[0]["id"])
        self.assertEqual(len(entity["revisions"]), 2)
        self.assertNotIn("capybara", entity["body"])

    def test_duplicate_observation_of_one_revision_is_indexed_once(self) -> None:
        item = record("alpha", [("user", "single axolotl")])
        self.add(item)
        self.add(item, export_uri="file:///synthetic/copy")
        result = self.fabric.index_hub(self.library)
        self.assertEqual((result["revisions_added"], result["chunks_added"]), (1, 1))

    def test_large_record_is_chunked_with_message_offsets(self) -> None:
        filler = "lorem ipsum dolor " * 300
        messages = [("user", filler) for _ in range(6)] + [("assistant", "the needle is pangolin")]
        messages.append(("user", "word " * 5000))
        item = record("big", messages)
        item["source_record"]["padding"] = "x" * (2 * 1024 * 1024)
        self.add(item)
        result = self.fabric.index_hub(self.library)
        self.assertGreater(result["chunks_added"], 4)
        self.assertEqual(result["segmenter"], {"package": "material-core", "version": CORE_VERSION})
        with closing(sqlite3.connect(self.fabric.db_path)) as connection:
            longest = connection.execute("SELECT MAX(LENGTH(body)) FROM hub_chunks_fts").fetchone()[0]
        self.assertLessEqual(longest, hub_index.CHUNK_CHARS)
        self.assertLess(self.fabric.db_path.stat().st_size, 1024 * 1024)
        hit = self.search("pangolin")[0]
        self.assertLessEqual(hit["message_offset"], 6)
        self.assertTrue(hit["path"].endswith(f"#message={hit['message_offset']}"))

    def test_secrets_are_redacted_and_missing_titles_are_derived(self) -> None:
        secret = "ghp_" + "a1B2" * 9
        self.add(record("alpha", [("user", f"flamingo token {secret} in  the\nlog")]))
        self.fabric.index_hub(self.library)
        hit = self.search("flamingo")[0]
        self.assertTrue(hit["title_is_derived"])
        with closing(sqlite3.connect(self.fabric.db_path)) as connection:
            stored = " ".join(row[0] + row[1] for row in connection.execute("SELECT title, body FROM hub_chunks_fts"))
        self.assertNotIn(secret, stored)
        self.assertIn("[REDACTED_SECRET]", stored)

    def test_workbench_escapes_markup_in_indexed_text(self) -> None:
        from control_plane.ui import _snippet_html
        self.add(record("alpha", [("user", "<script>alert(1)</script> beside the meerkat <img src=x onerror=y>")]))
        self.fabric.index_hub(self.library)
        rendered = _snippet_html(self.search("meerkat")[0]["snippet"])
        self.assertIn("<mark>meerkat</mark>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_hub_only_search_never_builds_the_fabric_cache(self) -> None:
        empty = self.fabric.search_hub("anything")
        self.assertEqual((empty["status"]["built"], empty["results"]), (False, []))
        self.assertFalse(self.fabric.db_path.exists())
        self.add(record("alpha", [("user", "older wombat")], updated_at="2026-01-02T00:00:00Z"))
        self.add(record("beta", [("user", "newer wombat")], updated_at="2026-02-02T00:00:00Z"))
        self.fabric.index_hub(self.library)
        found = self.fabric.search_hub("wombat", limit=1)
        self.assertEqual((len(found["results"]), found["status"]["conversations"]), (1, 2))
        self.assertNotIn("rank_score", found["results"][0])
        browse = self.fabric.search_hub("")["results"]
        self.assertEqual([item["updated_at"][:7] for item in browse], ["2026-02", "2026-01"])
        self.assertEqual(self.fabric.search_hub("!!!")["results"], [])
        self.assertFalse(self.fabric.freshness()["built"])
        for limit in (0, 51, True, "5"):
            with self.assertRaises(ValueError):
                self.fabric.search_hub("wombat", limit=limit)

    def test_mcp_search_includes_hub_text_only_on_request(self) -> None:
        from control_plane.mcp_server import search_fabric, tool_contracts
        from control_plane.phone_home import PhoneHomeError
        self.add(record("alpha", [("user", "requested echidna")]))
        self.fabric.index_hub(self.library)
        self.fabric.rebuild(include_conversations=False)  # keep the tool's cache check synthetic
        service = SimpleNamespace(fabric=self.fabric)
        default = search_fabric(service, {"query": "echidna"})
        self.assertEqual(default["results"], [])
        self.assertNotIn("conversation_hub", default)
        opted = search_fabric(service, {"query": "echidna", "include_conversation_hub": True, "limit": 5})
        self.assertEqual([item["source"] for item in opted["results"]], ["conversation-hub"])
        self.assertEqual(opted["conversation_hub"]["revisions"], 1)
        self.assertIn("untrusted", opted["notice"])
        for arguments in ({"query": "echidna", "include_conversation_hub": "yes"},
                          {"query": "echidna", "limit": 51}, {"query": "echidna", "limit": True},
                          {"query": None}, {"query": "echidna", "kind": 3}):
            with self.assertRaises(PhoneHomeError):
                search_fabric(service, arguments)
        contract = next(item for item in tool_contracts() if item["name"] == "devnet_search_fabric")
        self.assertEqual(contract["inputSchema"]["properties"]["include_conversation_hub"],
                         {"type": "boolean", "default": False})

    def test_conversations_tab_panel_lists_escaped_hub_matches(self) -> None:
        from control_plane.ui import ControlPlaneWorkbench
        workbench = SimpleNamespace(fabric=self.fabric)
        panel = ControlPlaneWorkbench.render_hub_library_panel
        self.assertIn("not indexed", panel(workbench, "numbat"))
        item = record("alpha", [("user", "<b>bold</b> numbat <script>x</script>")], title="<i>Numbat</i> notes")
        self.add(item)
        self.fabric.index_hub(self.library)
        html = panel(workbench, "numbat")
        self.assertIn("1 conversations, 1 revisions", html)
        self.assertIn("<mark>numbat</mark>", html)
        self.assertIn(item["id"], html)
        self.assertIn(item["revision"], html)
        self.assertIn(f"entity=hub:{item['id']}", html)
        for raw in ("<script>", "<b>bold", "<i>Numbat"):
            self.assertNotIn(raw, html)
        self.assertIn("No indexed conversation matches", panel(workbench, "absent"))
        self.assertIn("most recently updated (1)", panel(workbench, ""))

    def test_fabric_rebuild_keeps_the_hub_index(self) -> None:
        self.add(record("alpha", [("user", "durable tapir")]))
        self.fabric.index_hub(self.library)
        self.fabric.rebuild(include_conversations=False)
        self.assertEqual(len(self.search("tapir")), 1)
        freshness = self.fabric.freshness()
        self.assertTrue(freshness["built"])
        self.assertEqual(freshness["conversation_hub"]["revisions"], 1)
        self.assertIsNotNone(freshness["conversation_hub"]["indexed_at"])

    def test_incompatible_libraries_are_refused_without_touching_the_index(self) -> None:
        self.add(record("alpha", [("user", "stable heron")]))
        self.fabric.index_hub(self.library)
        self.assert_error("unavailable", self.root / "absent.sqlite")
        self.assert_error("unavailable", self.library.parent)
        for pragma in ("application_id = 7", "user_version = 2"):
            other = self.root / f"{pragma.split()[0]}.sqlite"
            other.write_bytes(self.library.read_bytes())
            with closing(sqlite3.connect(other)) as connection:
                connection.execute(f"PRAGMA {pragma}")
                connection.commit()
            self.assert_error("schema_incompatible", other)
        unmarked = self.root / "unmarked.sqlite"
        with closing(sqlite3.connect(unmarked)) as connection:
            connection.execute("CREATE TABLE notes (text TEXT)")
            connection.commit()
        size = unmarked.stat().st_size
        self.assert_error("schema_incompatible", unmarked)
        self.assertEqual(unmarked.stat().st_size, size)
        self.assertEqual(len(self.search("heron")), 1)

    def test_future_or_malformed_record_fails_without_echoing_content(self) -> None:
        future = record("future", [("user", "confidential ibis")])
        future["schema_version"] = 2
        bad_role = record("role", [("narrator", "confidential ibis")])
        for item in (future, bad_role):
            self.add(item)
            with self.assertRaises(ConversationLibraryError) as caught:
                self.fabric.index_hub(self.library)
            self.assertEqual(caught.exception.code, "schema_incompatible")
            self.assertNotIn("ibis", str(caught.exception))
            self.remove(item)
        self.assertEqual(self.search("ibis"), [])

    def test_exclusive_writer_reports_busy(self) -> None:
        self.add(record("alpha", [("user", "locked lemur")]))
        with closing(sqlite3.connect(self.library, isolation_level=None)) as writer:
            writer.execute("PRAGMA locking_mode = EXCLUSIVE")
            writer.execute("BEGIN EXCLUSIVE")
            self.assert_error("library_busy")
            writer.rollback()

    def test_library_is_never_modified(self) -> None:
        self.add(record("alpha", [("user", "untouched okapi")]))
        before = hashlib.sha256(self.library.read_bytes()).hexdigest()
        self.fabric.index_hub(self.library)
        self.fabric.index_hub(self.library)
        self.assertEqual(hashlib.sha256(self.library.read_bytes()).hexdigest(), before)
        self.assertEqual(sorted(path.name for path in self.library.parent.iterdir()), ["library.sqlite"])

    def test_cli_prints_counts_only_and_structured_errors(self) -> None:
        self.add(record("alpha", [("user", "private kinkajou details")], title="Kinkajou"))
        base = ["--factory-root", str(self.factory), "--data-dir", str(self.root / "cli-data"), "fabric", "index-hub"]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(base + ["--library", str(self.library)])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["revisions_added"], 1)
        self.assertNotIn("kinkajou", out.getvalue().lower())
        self.assertTrue((self.root / "cli-data" / "control_plane_fabric.sqlite").is_file())
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(base + ["--library", str(self.root / "absent.sqlite")])
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertEqual(json.loads(err.getvalue())["code"], "unavailable")


if __name__ == "__main__":
    unittest.main()
