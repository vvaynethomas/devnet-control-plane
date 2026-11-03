import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

from control_plane.conversation_hub_adapter import read_legacy_sessions, read_local_sessions
from control_plane.handoff import discover_antigravity_sessions, parse_session_turns
from control_plane.fabric import _harvest_antigravity_sessions, _harvest_copilot_sessions
from control_plane.conversations import UnifiedConversationHub
from control_plane.conversation_library import ConversationLibraryError, _configured_hub_api
from control_plane.ui import ControlPlaneWorkbench


class ConversationHubAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.brain_root = self.home / ".gemini" / "antigravity" / "brain"
        self.session_dir = self.brain_root / "session-a"
        transcript = self.session_dir / ".system_generated" / "logs" / "transcript.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(
            "\n".join([
                json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>hello synthetic</USER_REQUEST>", "created_at": "2025-01-01T10:00:00Z"}),
                json.dumps({"type": "PLANNER_RESPONSE", "content": "synthetic reply", "created_at": "2025-01-01T10:00:01Z"}),
            ]) + "\n",
            encoding="utf-8",
        )

        self.vscode_root = self.home / "Code" / "User" / "workspaceStorage"
        vscode_dir = self.vscode_root / "workspace-a" / "chatSessions"
        vscode_dir.mkdir(parents=True)
        (vscode_dir / "chat-a.jsonl").write_text(
            "\n".join([
                json.dumps({"v": {"creationDate": 1735725600000, "inputText": "synthetic vscode prompt"}}),
                json.dumps({"v": "synthetic vscode answer"}),
            ]) + "\n",
            encoding="utf-8",
        )

        self.cli_root = self.home / ".copilot" / "session-state"
        cli_dir = self.cli_root / "session-b"
        cli_dir.mkdir(parents=True)
        (cli_dir / "events.jsonl").write_text(
            "\n".join([
                json.dumps({"timestamp": "2025-01-01T10:59:59Z", "role": "assistant", "message": "synthetic unassigned prelude"}),
                json.dumps({"timestamp": "2025-01-01T11:00:00Z", "role": "user", "message": "synthetic cli prompt"}),
                json.dumps({"timestamp": "2025-01-01T11:00:00.500Z", "role": "tool", "message": "synthetic tool output"}),
                json.dumps({"timestamp": "2025-01-01T11:00:01Z", "role": "assistant", "message": "synthetic cli answer"}),
            ]) + "\n",
            encoding="utf-8",
        )

        self.database = self.root / "conversations_hub.sqlite"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "CREATE TABLE imported_chats (session_id TEXT PRIMARY KEY, platform TEXT NOT NULL, "
                "model TEXT NOT NULL, title TEXT NOT NULL, workspace TEXT, created_date TEXT, "
                "raw_content TEXT NOT NULL, turn_count INTEGER, est_tokens INTEGER)"
            )
            connection.execute(
                "INSERT INTO imported_chats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("synthetic-import", "Synthetic", "Synthetic model", "Synthetic title", "Fixture",
                 "2025-01-01T12:00:00Z", "synthetic user paragraph\n\nsynthetic assistant paragraph", 2, 20),
            )
            connection.commit()

    def test_explicit_source_readers_project_only_synthetic_roots(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter integration coverage")
            raise
        ag_sessions, ag_diagnostics, _ = read_local_sessions(
            "antigravity", self.brain_root, archive_key="test-antigravity", max_sessions=20,
        )
        vscode_sessions, _, _ = read_local_sessions(
            "vscode-copilot", self.vscode_root, archive_key="test-vscode", max_sessions=25,
        )
        cli_sessions, _, _ = read_local_sessions(
            "copilot-cli", self.cli_root, archive_key="test-cli", max_sessions=25,
        )
        database_before = self.database.read_bytes()
        imported, _, _ = read_legacy_sessions(self.database, archive_key="test-imports")

        self.assertIn("synthetic reply", ag_sessions[0]["turns"][0]["assistant_responses"][0])
        self.assertTrue(any("no verified stable schema/version" in note for note in ag_diagnostics))
        self.assertIn("synthetic vscode answer", vscode_sessions[0]["turns"][0]["assistant_responses"][0])
        self.assertEqual(cli_sessions[0]["turns"][0]["user_prompt"], "synthetic cli prompt")
        self.assertEqual(
            cli_sessions[0]["turns"][0]["other_messages"][0]["content"],
            "synthetic tool output",
        )
        self.assertEqual(cli_sessions[0]["unassigned_messages"][0]["content"], "synthetic unassigned prelude")
        self.assertEqual(imported[0]["session_id"], "synthetic-import")
        self.assertTrue(imported[0]["source_path"].startswith("database://"))
        self.assertEqual(self.database.read_bytes(), database_before)

    def test_fabric_cli_uses_hub_and_antigravity_preserves_selection(self) -> None:
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
             patch("control_plane.handoff.os.path.expanduser", return_value=str(self.home)):
            fabric_ag = _harvest_antigravity_sessions()
            fabric_cli = _harvest_copilot_sessions()
            discovered = discover_antigravity_sessions()
            turns = parse_session_turns(Path(discovered[0]["transcript_path"]))

        self.assertIn("[USER]: hello synthetic", fabric_ag[0]["body"])
        self.assertIn("synthetic cli prompt", fabric_cli[0]["body"])
        self.assertIn("synthetic unassigned prelude", fabric_cli[0]["body"])
        self.assertEqual(discovered[0]["session_id"], "session-a")
        self.assertEqual(turns[0]["user_prompt"], "hello synthetic")
        self.assertEqual(turns[0]["assistant_responses"], ["synthetic reply"])

    def test_base_install_keeps_legacy_readers_for_explicit_synthetic_sources(self) -> None:
        hub = UnifiedConversationHub(data_dir=self.root / "dncp-data")
        with patch.object(hub, "_get_hub_api", return_value=None):
            antigravity = hub.scan_antigravity(self.brain_root)
            vscode = hub.scan_vscode_copilot(self.vscode_root)
            cli = hub.scan_copilot_cli(self.cli_root)
            imported = hub.get_imported_chats()

        self.assertEqual(antigravity[0]["full_session_id"], "session-a")
        self.assertEqual(vscode[0]["full_session_id"], "chat-a")
        self.assertEqual(cli[0]["full_session_id"], "session-b")
        self.assertEqual(imported, [])

    def test_incompatible_installed_hub_does_not_fall_back(self) -> None:
        hub = UnifiedConversationHub(data_dir=self.root / "dncp-data")
        incompatible = ConversationLibraryError(
            "hub_incompatible", "wrong installed commit", 503,
        )
        with patch("control_plane.conversations._configured_hub_api", side_effect=incompatible):
            with self.assertRaises(ConversationLibraryError):
                hub.scan_antigravity(self.brain_root)

    def test_base_install_fallbacks_remain_explicit_and_synthetic(self) -> None:
        unavailable = ConversationLibraryError(
            "hub_unavailable", "optional package unavailable", 503,
        )
        with patch(
            "control_plane.conversation_hub_adapter._configured_hub_api",
            side_effect=unavailable,
        ), patch("control_plane.fabric._configured_hub_api", side_effect=unavailable), \
             patch("control_plane.handoff._configured_hub_api", side_effect=unavailable), \
             patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
             patch("control_plane.handoff.os.path.expanduser", return_value=str(self.home)):
            fabric_ag = _harvest_antigravity_sessions()
            fabric_cli = _harvest_copilot_sessions()
            discovered = discover_antigravity_sessions()
            turns = parse_session_turns(
                self.session_dir / ".system_generated" / "logs" / "transcript.jsonl",
            )

        self.assertIn("hello synthetic", fabric_ag[0]["body"])
        self.assertIn("synthetic cli prompt", fabric_cli[0]["body"])
        self.assertEqual(discovered[0]["session_id"], "session-a")
        self.assertEqual(turns[0]["user_prompt"], "hello synthetic")

    def test_ui_reports_adapter_revision_and_escapes_diagnostics(self) -> None:
        workbench = ControlPlaneWorkbench.__new__(ControlPlaneWorkbench)
        workbench.factory_root = self.root
        workbench.network_root = self.root
        workbench.conversations_hub = SimpleNamespace(get_all_conversations=lambda **_: {
            "summary": {
                "total_sessions": 1, "filtered_sessions": 1, "total_turns": 1,
                "est_total_tokens": 10, "est_input_tokens": 5, "est_output_tokens": 5,
                "platforms": {"Copilot CLI": 1}, "models": {"Synthetic": 1},
            },
            "sessions": [{
                "session_id": "CLI-test", "full_session_id": "test", "platform": "Copilot CLI",
                "model": "Synthetic", "title": "Synthetic session", "workspace": "Fixture",
                "created_date": "2025-01-01", "turn_count": 1, "est_total_tokens": 10,
                "est_input_tokens": 5, "est_output_tokens": 5, "source_path": "synthetic://source",
                "turns": [{
                    "turn_index": 1, "timestamp": "2025-01-01", "user_prompt": "synthetic prompt",
                    "assistant_responses": ["synthetic answer"],
                    "other_messages": [{
                        "role": "tool", "source_role": "tool", "content": "<tool> output",
                    }],
                }],
                "unassigned_messages": [{
                    "role": "unknown", "source_role": "unknown", "content": "<unassigned> source",
                }],
            }],
            "source_adapter": {
                "implementation": "conversation-hub",
                "version": "0.1.1",
                "revision": "186fcae50f030ff72909326db1e3b5b79ff7869c",
                "diagnostics": ["<source> is bounded"],
            },
        })
        with patch(
            "control_plane.handoff.compile_context_handoff",
            return_value={"markdown": "synthetic handoff"},
        ):
            rendered = workbench.render_conversations_tab()

        self.assertIn("conversation-hub 0.1.1", rendered)
        self.assertIn("186fcae50f030ff72909326db1e3b5b79ff7869c", rendered)
        self.assertIn("&lt;source&gt; is bounded", rendered)
        self.assertIn("&lt;tool&gt; output", rendered)
        self.assertIn("&lt;unassigned&gt; source", rendered)


if __name__ == "__main__":
    unittest.main()
