import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

from control_plane.conversation_hub_adapter import read_legacy_sessions, read_local_sessions
from control_plane.handoff import (
    compile_context_handoff, discover_antigravity_sessions, parse_session_turns,
)
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

    def test_handoff_round_trips_literal_escape_and_space_paths(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter integration coverage")
            raise

        expected = {
            "session%20literal": "synthetic percent-name prompt",
            "session with space": "synthetic space-name prompt",
        }
        for index, (session_name, prompt) in enumerate(expected.items()):
            transcript = (
                self.brain_root / session_name / ".system_generated" / "logs" / "transcript.jsonl"
            )
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                json.dumps({
                    "type": "USER_INPUT",
                    "content": f"<USER_REQUEST>{prompt}</USER_REQUEST>",
                    "created_at": "2025-01-01T10:00:00Z",
                }) + "\n",
                encoding="utf-8",
            )
            session_dir = transcript.parent.parent.parent
            os.utime(session_dir, (1_700_000_000 + index, 1_700_000_000 + index))

        with patch("control_plane.handoff.os.path.expanduser", return_value=str(self.home)):
            discovered = discover_antigravity_sessions()
            turns_by_session = {
                session["session_id"]: parse_session_turns(Path(session["transcript_path"]))
                for session in discovered
                if session["session_id"] in expected
            }

        self.assertEqual(set(turns_by_session), set(expected))
        for session_name, prompt in expected.items():
            transcript_path = Path(
                next(session["transcript_path"] for session in discovered if session["session_id"] == session_name)
            )
            self.assertTrue(transcript_path.is_file())
            self.assertEqual(transcript_path.parent.parent.parent.name, session_name)
            self.assertEqual(turns_by_session[session_name][0]["user_prompt"], prompt)

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
        ), patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
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

    def _create_ordered_antigravity_sessions(self, count: int) -> None:
        self.brain_root.mkdir(parents=True, exist_ok=True)
        base_time = 1_700_000_000
        for index in range(count):
            session_dir = self.brain_root / f"ordered-{index:02}"
            session_dir.mkdir()
            transcript = session_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if index not in {25}:
                transcript.parent.mkdir(parents=True)
                if index == 0:
                    transcript.write_text("{ malformed but outside every tested cap }\n", encoding="utf-8")
                elif index == 26:
                    transcript.write_text(
                        json.dumps({"type": "UNSUPPORTED_EVENT", "content": "synthetic unknown event"}) + "\n",
                        encoding="utf-8",
                    )
                elif index == 23:
                    transcript.write_text("", encoding="utf-8")
                else:
                    events = []
                    if index != 24:
                        events.append({
                            "type": "USER_INPUT",
                            "content": f"<USER_REQUEST>synthetic prompt {index}</USER_REQUEST>",
                            "created_at": f"2025-01-01T10:{index:02}:00Z",
                        })
                    if index != 5:
                        response = {
                            "type": "PLANNER_RESPONSE",
                            "content": f"synthetic answer {index}",
                            "created_at": f"2025-01-01T10:{index:02}:01Z",
                        }
                        if index == 7:
                            response["tool_calls"] = [{
                                "function": {
                                    "name": "synthetic_tool",
                                    "arguments": {"toolSummary": "synthetic invocation"},
                                },
                            }]
                        events.append(response)
                    transcript.write_text(
                        "".join(json.dumps(event) + "\n" for event in events),
                        encoding="utf-8",
                    )
            os.utime(session_dir, (base_time + index, base_time + index))

    def test_antigravity_directory_first_caps_order_diagnostics_and_handoff_projection(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for Antigravity contract coverage")
            raise
        self.home = self.root / "ordered-home"
        self.brain_root = self.home / ".gemini" / "antigravity" / "brain"
        self._create_ordered_antigravity_sessions(27)
        hub = UnifiedConversationHub(data_dir=self.root / "dncp-data", factory_root=self.root)
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
             patch("control_plane.handoff.os.path.expanduser", return_value=str(self.home)):
            manager = hub.scan_antigravity(self.brain_root)
            fabric = _harvest_antigravity_sessions()
            handoff = discover_antigravity_sessions()
            parsed = parse_session_turns(
                self.brain_root / "ordered-07" / ".system_generated" / "logs" / "transcript.jsonl",
            )
            handoff_packet = compile_context_handoff(
                session_id="ordered-07",
                factory_root=self.root,
                network_root=self.root,
            )
        selected, diagnostics, _ = read_local_sessions(
            "antigravity",
            self.brain_root,
            archive_key="test-directory-first",
            max_sessions=25,
            selection_policy="directory-first",
        )

        self.assertTrue(diagnostics)
        self.assertTrue(any(
            "Directory-first selection capped at 25 session directories" in item
            for item in diagnostics
        ))
        self.assertTrue(any(
            "lacked the expected transcript path" in item
            for item in diagnostics
        ))
        selected_ids = [session["full_session_id"] for session in selected]
        self.assertEqual(
            selected_ids,
            sorted(selected_ids, key=lambda value: int(value.rsplit("-", 1)[1]), reverse=True),
        )
        self.assertNotIn("ordered-00", set(selected_ids))
        self.assertNotIn("ordered-01", set(selected_ids))
        self.assertNotIn("ordered-25", set(selected_ids))
        self.assertIn("ordered-23", set(selected_ids))
        self.assertIn("ordered-26", set(selected_ids))
        fabric_ids = {Path(record["abs_path"]).parents[2].name for record in fabric}
        self.assertNotIn("ordered-06", fabric_ids)
        self.assertIn("ordered-07", fabric_ids)
        self.assertIn("ordered-06", {session["full_session_id"] for session in manager})
        self.assertIn("ordered-24", fabric_ids)
        self.assertNotIn("ordered-23", {session["full_session_id"] for session in manager})
        self.assertNotIn("ordered-26", fabric_ids)
        self.assertNotIn("ordered-26", {session["full_session_id"] for session in manager})
        self.assertNotIn("ordered-24", {session["session_id"] for session in handoff})
        self.assertNotIn("ordered-25", {session["full_session_id"] for session in manager})
        self.assertTrue(any("synthetic_tool" in tool for tool in parsed[0]["tool_calls"]))
        self.assertIn("synthetic invocation", parsed[0]["tool_calls"][0])
        self.assertIn("synthetic_tool", handoff_packet["markdown"])

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
                "version": "0.1.4",
                "revision": "11eb07caf7ce45eb35111c9ef017ad9c21de0ad2",
                "diagnostics": ["<source> is bounded"],
            },
        })
        with patch(
            "control_plane.handoff.compile_context_handoff",
            return_value={"markdown": "synthetic handoff"},
        ):
            rendered = workbench.render_conversations_tab()

        self.assertIn("conversation-hub 0.1.4", rendered)
        self.assertIn("11eb07caf7ce45eb35111c9ef017ad9c21de0ad2", rendered)
        self.assertIn("&lt;source&gt; is bounded", rendered)
        self.assertIn("&lt;tool&gt; output", rendered)
        self.assertIn("&lt;unassigned&gt; source", rendered)


if __name__ == "__main__":
    unittest.main()
