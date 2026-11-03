"""Synthetic PRJ-0006 persistence-contract integration; no personal source discovery."""

from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from importlib.metadata import PackageNotFoundError
from pathlib import PurePosixPath
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from control_plane.cli import main
from control_plane.conversation_library import (
    APPLICATION_ID, ConversationLibraryError, MAX_LIBRARY_BYTES, MAX_OBSERVATIONS,
    MAX_RECORD_BYTES, MAX_TOTAL_BYTES, _configured_snapshot_reader, read_conversation_library,
)


def fixture(platform: str = "chatgpt", revision: str = "b" * 64) -> dict:
    return {
        "schema_version": 1, "id": "a" * 64, "revision": revision,
        "source": {
            "archive_key": "synthetic-archive", "platform": platform, "edition": "bulk-export",
            "session_id": "session-1", "source_id": None, "source_name": None,
            "native_session_id": "native-1",
        },
        "created_at": None, "updated_at": "2026-11-01T12:00:00+00:00",
        "source_current_node_id": "branch-b",
        "messages": [
            {
                "id": "c" * 64, "position": 1, "role": "user", "source_role": "user",
                "content": "  synthetic prompt\n", "timestamp": None, "pointer": "/0/mapping/root/message",
                "source_event_id": "root", "parent_source_event_id": None,
                "child_source_event_ids": ["branch-a", "branch-b"],
            },
            {
                "id": "d" * 64, "position": 3, "role": "unknown", "source_role": "future-role",
                "content": "Synthetic alternate branch \u2603", "timestamp": None,
                "pointer": "/0/mapping/branch-b/message", "source_event_id": "branch-b",
                "parent_source_event_id": "root", "child_source_event_ids": [],
            },
        ],
        "provenance": {
            "producer": "synthetic-exporter", "declared_version": "synthetic-1",
            "export_uri": "file:///not-accessed/synthetic.json", "export_sha256": "e" * 64, "pointer": "/0",
            "observed_at": "2026-11-02T21:00:00.123456Z",
        },
        "source_record": {"mapping": {"structural-node": {"message": None}}, "unparsed": "preserve"},
        "limitations": ["Synthetic fixture; tools and original-source freshness unknown."],
    }


def synthetic_read_snapshot(path: Path):
    @contextmanager
    def snapshot():
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None,
        )
        try:
            connection.execute("BEGIN")
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Not a supported library")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Not a supported library")
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    return snapshot()


class ConversationLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reader_patcher = patch(
            "control_plane.conversation_library._configured_snapshot_reader",
            return_value=(
                synthetic_read_snapshot,
                {
                    "implementation": "conversation-hub",
                    "version": "0.1.3",
                    "revision": "654291bfcb5b928f86aec75acd8cf58336837412",
                },
            ),
        )
        self.reader_patcher.start()
        self.addCleanup(self.reader_patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "private # \u2603" / "library.sqlite"
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

    def add(self, record: dict) -> None:
        provenance = record["provenance"]
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO exports VALUES (?, ?)", (provenance["export_sha256"], b"synthetic raw export"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO revisions VALUES (?, ?)", (record["id"], record["revision"]),
            )
            connection.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?)", (
                record["id"], record["revision"], provenance["export_sha256"], provenance["export_uri"],
                json.dumps(record, ensure_ascii=False),
            ))

    def assert_error(self, code: str, library: Path | None = None, expected: str | None = None) -> None:
        with self.assertRaises(ConversationLibraryError) as caught:
            read_conversation_library(library or self.library, expected)
        self.assertEqual(caught.exception.code, code)

    def test_preserves_every_source_observation_revision_branch_and_limitation(self) -> None:
        records = [fixture()]
        copied = deepcopy(records[0])
        copied["provenance"]["export_uri"] = "file:///not-accessed/copied.json"
        records.append(copied)
        records.append(fixture(revision="f" * 64))
        other = fixture("antigravity-history")
        other["id"] = "1" * 64
        records.append(other)
        for record in records:
            self.add(record)
        before = self.library.read_bytes()
        result = read_conversation_library(self.library)
        self.assertCountEqual(result["observations"], records)
        self.assertEqual(result["source_freshness"], "unknown")
        self.assertEqual(result["observation_time"], "per_observation")
        self.assertEqual(result["observations"][0]["provenance"]["observed_at"], "2026-11-02T21:00:00.123456Z")
        self.assertEqual(result["snapshot_check"], "not_requested")
        self.assertIn("never followed", result["diagnostics"][1])
        self.assertEqual(result["contract"]["schema_version"], 1)
        self.assertEqual(result["contract"]["producer_revision"], "11c362c621727a331a1ecf9ffee40220d8a6d373")
        self.assertEqual(result["library_reader"]["revision"], "654291bfcb5b928f86aec75acd8cf58336837412")
        self.assertEqual(before, self.library.read_bytes())
        self.assertEqual(list(self.library.parent.iterdir()), [self.library])

    def test_empty_library_is_not_unavailable_or_fresh_source(self) -> None:
        result = read_conversation_library(self.library)
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["source_freshness"], "unknown")
        self.assertEqual(result["observation_time"], "per_observation")

    def test_import_observation_timestamp_required_and_utc(self) -> None:
        self.add(fixture())
        record = fixture()
        for value in ("not-a-date", "2026-11-02T21:00:00", "2026-11-02T21:00:00+00:00",
                      "2026-11-02T22:00:00+01:00", None, 123):
            with self.subTest(value=value):
                record["provenance"]["observed_at"] = value
                with closing(sqlite3.connect(self.library)) as connection, connection:
                    connection.execute("UPDATE observations SET normalized_json = ?", (json.dumps(record),))
                self.assert_error("schema_incompatible")
        record = fixture()
        del record["provenance"]["observed_at"]
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute("UPDATE observations SET normalized_json = ?", (json.dumps(record),))
        self.assert_error("schema_incompatible")

    def test_stale_snapshot_after_import_or_deletion_no_cache_fallback(self) -> None:
        self.add(fixture())
        snapshot = read_conversation_library(self.library)["snapshot_sha256"]
        self.assertEqual(read_conversation_library(self.library, snapshot)["snapshot_check"], "matches")
        self.add(fixture(revision="f" * 64))
        self.assert_error("stale_snapshot", expected=snapshot)
        changed = read_conversation_library(self.library)["snapshot_sha256"]
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute("DELETE FROM observations")
            connection.execute("DELETE FROM revisions")
            connection.execute("DELETE FROM exports")
        self.assert_error("stale_snapshot", expected=changed)
        self.assertEqual(read_conversation_library(self.library)["observations"], [])
        self.library.unlink()
        self.assert_error("unavailable")

    def test_snapshot_is_order_and_json_format_independent(self) -> None:
        self.add(fixture())
        self.add(fixture(revision="f" * 64))
        snapshot = read_conversation_library(self.library)["snapshot_sha256"]
        with closing(sqlite3.connect(self.library)) as connection, connection:
            rows = connection.execute("SELECT * FROM observations").fetchall()
            connection.execute("DELETE FROM observations")
            for row in reversed(rows):
                connection.execute(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, ?)",
                    (*row[:4], json.dumps(json.loads(row[4]), indent=2, sort_keys=True)),
                )
        self.assertEqual(read_conversation_library(self.library)["snapshot_sha256"], snapshot)

    def test_missing_corrupt_directory_and_invalid_digest(self) -> None:
        missing = self.root / "not-created.sqlite"
        self.assert_error("unavailable", missing)
        self.assertFalse(missing.exists())
        bad = self.root / "corrupt.sqlite"
        bad.write_bytes(b"not sqlite")
        self.assert_error("unavailable", bad)
        self.assert_error("unavailable", self.library.parent)
        self.assert_error("invalid_request", expected="not-a-digest")

    def test_database_versions_and_table_schema_are_refused(self) -> None:
        for pragma, value in (("application_id", 0), ("user_version", 2)):
            with self.subTest(pragma=pragma):
                with closing(sqlite3.connect(self.library)) as connection:
                    old = connection.execute(f"PRAGMA {pragma}").fetchone()[0]
                    connection.execute(f"PRAGMA {pragma} = {value}")
                before = self.library.read_bytes()
                self.assert_error("schema_incompatible")
                self.assertEqual(before, self.library.read_bytes())
                with closing(sqlite3.connect(self.library)) as connection:
                    connection.execute(f"PRAGMA {pragma} = {old}")
        with closing(sqlite3.connect(self.library)) as connection:
            connection.execute("ALTER TABLE observations RENAME COLUMN normalized_json TO old_json")
        self.assert_error("schema_incompatible")

    def test_view_in_place_of_table_is_refused(self) -> None:
        with closing(sqlite3.connect(self.library)) as connection:
            connection.execute("DROP TABLE observations")
            connection.execute("CREATE VIEW observations AS SELECT 1")
        self.assert_error("schema_incompatible")

    def test_malformed_normalized_records_fail_whole_read_without_content_in_error(self) -> None:
        self.add(fixture())
        base = fixture()
        mutations = [
            lambda r: r.update(schema_version=True),
            lambda r: r.update(schema_version=2),
            lambda r: r.update(messages={}),
            lambda r: r.update(source=[]),
            lambda r: r.update(limitations="not a list"),
            lambda r: r["provenance"].update(export_sha256="0" * 64),
            lambda r: r["messages"][0].update(position=-1),
            lambda r: r["messages"][0].update(position=True),
            lambda r: r["messages"][1].update(position=1),
            lambda r: r["messages"][0].update(child_source_event_ids=[42]),
            lambda r: r["messages"][0].update(content=None),
            lambda r: r.update(id="not-digest"),
            lambda r: r["source_record"].update(invalid_unicode="\ud800"),
        ]
        raw_values = ["not json", '{"schema_version":1,"schema_version":1}', '{"secret":NaN}']
        for mutate in mutations:
            record = deepcopy(base)
            mutate(record)
            raw_values.append(json.dumps(record))
        for raw in raw_values:
            with self.subTest(raw=raw):
                with closing(sqlite3.connect(self.library)) as connection, connection:
                    connection.execute("UPDATE observations SET normalized_json = ?", (raw,))
                with self.assertRaises(ConversationLibraryError) as caught:
                    read_conversation_library(self.library)
                self.assertEqual(caught.exception.code, "schema_incompatible")
                self.assertNotIn("synthetic prompt", str(caught.exception))

    def test_bounded_record_count_bytes_total_and_library_size(self) -> None:
        self.add(fixture())
        for name, value in (("MAX_OBSERVATIONS", 0), ("MAX_RECORD_BYTES", 1), ("MAX_TOTAL_BYTES", 1),
                            ("MAX_LIBRARY_BYTES", 1)):
            with self.subTest(name=name), patch(f"control_plane.conversation_library.{name}", value):
                self.assert_error("limit_exceeded")
        self.assertEqual(MAX_OBSERVATIONS, 256)
        self.assertEqual(MAX_RECORD_BYTES, 256 * 1024)
        self.assertEqual(MAX_TOTAL_BYTES, 4 * 1024 * 1024)
        self.assertEqual(MAX_LIBRARY_BYTES, 32 * 1024 * 1024)

    def test_exact_record_limit_and_one_over(self) -> None:
        record = fixture()
        raw_size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        record["source_record"]["padding"] = "x" * (MAX_RECORD_BYTES - raw_size - len(', "padding": ""'))
        self.assertEqual(len(json.dumps(record, ensure_ascii=False).encode("utf-8")), MAX_RECORD_BYTES)
        self.add(record)
        self.assertEqual(len(read_conversation_library(self.library)["observations"]), 1)
        with closing(sqlite3.connect(self.library)) as connection, connection:
            record["source_record"]["padding"] += "x"
            connection.execute("UPDATE observations SET normalized_json = ?", (json.dumps(record, ensure_ascii=False),))
        self.assert_error("limit_exceeded")

    def test_exact_count_limit_and_one_over(self) -> None:
        for index in range(MAX_OBSERVATIONS):
            self.add(fixture(revision=f"{index:064x}"))
        self.assertEqual(len(read_conversation_library(self.library)["observations"]), MAX_OBSERVATIONS)
        self.add(fixture(revision="f" * 64))
        self.assert_error("limit_exceeded")

    def test_exact_total_bytes_and_one_over(self) -> None:
        record = fixture()
        raw_size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        record["source_record"]["padding"] = "x" * (MAX_RECORD_BYTES - raw_size - len(', "padding": ""'))
        for index in range(MAX_TOTAL_BYTES // MAX_RECORD_BYTES):
            record["revision"] = f"{index:064x}"
            self.add(record)
        self.assertEqual(len(read_conversation_library(self.library)["observations"]), 16)
        self.add(fixture(revision="f" * 64))
        self.assert_error("limit_exceeded")

    def test_exact_library_bytes_and_one_over(self) -> None:
        with self.library.open("r+b") as source:
            source.truncate(MAX_LIBRARY_BYTES)
        self.assertEqual(read_conversation_library(self.library)["observations"], [])
        with self.library.open("ab") as source:
            source.write(b"x")
        self.assert_error("limit_exceeded")

    def test_orphaned_observation_is_not_valid_provenance(self) -> None:
        self.add(fixture())
        with closing(sqlite3.connect(self.library)) as connection, connection:
            connection.execute("DELETE FROM exports")
        self.assert_error("schema_incompatible")

    def test_wal_read_snapshot_is_consistent_during_concurrent_writer(self) -> None:
        self.add(fixture())
        with closing(sqlite3.connect(self.library)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
        from control_plane.conversation_library import _validate_record
        original_validate = _validate_record
        inserted = False

        def insert_after_snapshot(raw: str, key: tuple[str, str, str, str]) -> dict:
            nonlocal inserted
            result = original_validate(raw, key)
            if not inserted:
                inserted = True
                self.add(fixture(revision="f" * 64))
            return result

        with patch("control_plane.conversation_library._validate_record", side_effect=insert_after_snapshot):
            snapshot = read_conversation_library(self.library)
        self.assertEqual(len(snapshot["observations"]), 1)
        self.assertEqual(len(read_conversation_library(self.library)["observations"]), 2)

    def test_published_read_snapshot_api_shape_is_supported_with_synthetic_provider(self) -> None:
        calls: list[Path] = []

        def producer_read_snapshot(path: Path):
            calls.append(path)
            return synthetic_read_snapshot(path)

        self.add(fixture())
        before = self.library.read_bytes()
        provider_info = {
            "implementation": "conversation-hub",
            "version": "0.1.3",
            "revision": "654291bfcb5b928f86aec75acd8cf58336837412",
        }
        with patch(
            "control_plane.conversation_library._configured_snapshot_reader",
            return_value=(producer_read_snapshot, provider_info),
        ):
            result = read_conversation_library(self.library)
        self.assertEqual(calls, [self.library.resolve()])
        self.assertEqual(result["observations"], [fixture()])
        self.assertEqual(result["library_reader"], provider_info)
        self.assertEqual(before, self.library.read_bytes())

    def test_missing_optional_hub_has_actionable_error_and_no_fallback(self) -> None:
        with patch(
            "control_plane.conversation_library.distribution",
            side_effect=PackageNotFoundError,
        ):
            with self.assertRaises(ConversationLibraryError) as caught:
                _configured_snapshot_reader()
        self.assertEqual(caught.exception.code, "hub_unavailable")
        self.assertIn("devnet-control-plane[conversation-hub]", str(caught.exception))
        self.assertIn("Python 3.12+", str(caught.exception))

    def test_wrong_installed_hub_commit_is_rejected(self) -> None:
        class WrongHubDistribution:
            version = "0.1.3"

            @staticmethod
            def read_text(name: str) -> str:
                return json.dumps({"vcs_info": {"commit_id": "0" * 40}})

        with patch(
            "control_plane.conversation_library.distribution",
            return_value=WrongHubDistribution(),
        ):
            with self.assertRaises(ConversationLibraryError) as caught:
                _configured_snapshot_reader()
        self.assertEqual(caught.exception.code, "hub_incompatible")
        self.assertIn("pinned v0.1.3 commit", str(caught.exception))

    def test_checked_distribution_loading_ignores_path_shadow_and_preloaded_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            distribution_root = root / "site-packages"
            package_dir = distribution_root / "conversation_hub"
            package_dir.mkdir(parents=True)
            (package_dir / "model.py").write_text("TOKEN = 'checked-distribution'\n", encoding="utf-8")
            library_path = package_dir / "library.py"
            library_path.write_text(
                "from .model import TOKEN\n"
                "def read_snapshot(path):\n"
                "    return TOKEN\n"
                "def read_conversations(path, *, limit=1000):\n"
                "    return ()\n",
                encoding="utf-8",
            )
            (package_dir / "copilot_export.py").write_text("class ImportFormatError(ValueError): pass\n", encoding="utf-8")
            (package_dir / "views.py").write_text(
                "def conversation_view(conversation): return conversation\n", encoding="utf-8",
            )
            (package_dir / "sources.py").write_text(
                "def read_antigravity_sessions(*args, **kwargs): pass\n"
                "def read_vscode_copilot_sessions(*args, **kwargs): pass\n"
                "def read_copilot_cli_sessions(*args, **kwargs): pass\n"
                "def read_legacy_imported_chats(*args, **kwargs): pass\n",
                encoding="utf-8",
            )
            shadow_dir = root / "shadow"
            shadow_package = shadow_dir / "conversation_hub"
            shadow_package.mkdir(parents=True)
            marker = root / "shadow-executed"
            (shadow_package / "__init__.py").write_text("", encoding="utf-8")
            (shadow_package / "library.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
                "def read_snapshot(path):\n"
                "    return 'shadow'\n",
                encoding="utf-8",
            )

            class CheckedDistribution:
                version = "0.1.3"
                files = [
                    PurePosixPath("conversation_hub/library.py"),
                    PurePosixPath("conversation_hub/model.py"),
                    PurePosixPath("conversation_hub/copilot_export.py"),
                    PurePosixPath("conversation_hub/views.py"),
                    PurePosixPath("conversation_hub/sources.py"),
                ]

                @staticmethod
                def read_text(name: str) -> str:
                    return json.dumps({
                        "url": "https://github.com/vvaynethomas/conversation-hub.git",
                        "vcs_info": {"commit_id": "654291bfcb5b928f86aec75acd8cf58336837412"},
                    })

                @staticmethod
                def locate_file(name: str) -> Path:
                    return distribution_root / name

            hostile_parent = ModuleType("conversation_hub")
            hostile_parent.__path__ = [str(shadow_package)]
            hostile_library = ModuleType("conversation_hub.library")
            hostile_library.read_snapshot = lambda path: "preloaded-shadow"
            with patch("control_plane.conversation_library.distribution", return_value=CheckedDistribution()):
                with patch.dict(sys.modules, {
                    "conversation_hub": hostile_parent,
                    "conversation_hub.library": hostile_library,
                }):
                    with patch("sys.path", [str(shadow_dir), *sys.path]):
                        reader, info = _configured_snapshot_reader()

            self.assertEqual(reader(None), "checked-distribution")
            self.assertEqual(Path(reader.__globals__["__file__"]), library_path)
            self.assertEqual(info["revision"], "654291bfcb5b928f86aec75acd8cf58336837412")
            self.assertFalse(marker.exists())

    def test_pinned_hub_reader_reads_synthetic_library_when_extra_is_installed(self) -> None:
        if importlib.util.find_spec("conversation_hub") is None:
            self.skipTest("Install the optional conversation-hub extra for package integration coverage")
        reader, reader_info = _configured_snapshot_reader()
        self.add(fixture())
        before = self.library.read_bytes()
        with patch(
            "control_plane.conversation_library._configured_snapshot_reader",
            return_value=(reader, reader_info),
        ):
            result = read_conversation_library(self.library)
        self.assertEqual(reader_info["implementation"], "conversation-hub")
        self.assertEqual(reader_info["version"], "0.1.3")
        self.assertEqual(reader_info["revision"], "654291bfcb5b928f86aec75acd8cf58336837412")
        self.assertEqual(result["observations"], [fixture()])
        self.assertEqual(before, self.library.read_bytes())

    def test_exclusive_writer_returns_redacted_busy_error(self) -> None:
        path = self.library.with_name("private-path-secret.sqlite")
        self.library.replace(path)
        writer = sqlite3.connect(path, isolation_level=None)
        writer.execute("BEGIN EXCLUSIVE")
        try:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                result = main(["conversation-library", "--library", str(path)])
            self.assertEqual(result, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(json.loads(err.getvalue())["code"], "library_busy")
            self.assertNotIn("private-path-secret", err.getvalue())
            self.assertNotIn(str(path), err.getvalue())
        finally:
            writer.rollback()
            writer.close()

    def test_unmarked_database_is_refused_without_initializing_or_echoing_path(self) -> None:
        path = self.root / "private-path-secret.sqlite"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE unrelated (secret TEXT)")
        before = path.read_bytes()
        with self.assertRaises(ConversationLibraryError) as caught:
            read_conversation_library(path)
        self.assertEqual(caught.exception.code, "schema_incompatible")
        self.assertNotIn(str(path), str(caught.exception))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.library.parent, path])

    def test_cli_no_phone_home_harvest_network_subprocess_or_runtime_storage(self) -> None:
        self.add(fixture())
        before = hashlib.sha256(self.library.read_bytes()).hexdigest()
        out, err = io.StringIO(), io.StringIO()
        with patch("control_plane.cli.PhoneHome", side_effect=AssertionError("no service")), \
             patch("control_plane.conversations.UnifiedConversationHub", side_effect=AssertionError("no harvest")), \
             patch("socket.socket", side_effect=AssertionError("no network")), \
             patch("subprocess.Popen", side_effect=AssertionError("no subprocess")), \
             redirect_stdout(out), redirect_stderr(err):
            code = main(["--data-dir", str(self.root / "unused-runtime"),
                         "conversation-library", "--library", str(self.library)])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(json.loads(out.getvalue())["observations"], [fixture()])
        self.assertFalse((self.root / "unused-runtime").exists())
        self.assertEqual(before, hashlib.sha256(self.library.read_bytes()).hexdigest())

    def test_cli_errors_are_nonzero_structured_and_have_no_partial_stdout(self) -> None:
        self.add(fixture())
        for extra, code in ((["--expected-snapshot", "0" * 64], "stale_snapshot"),
                            (["--expected-snapshot", "bad"], "invalid_request")):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                result = main(["conversation-library", "--library", str(self.library), *extra])
            self.assertEqual(result, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(json.loads(err.getvalue())["code"], code)
            self.assertNotIn("synthetic prompt", err.getvalue())


if __name__ == "__main__":
    unittest.main()
