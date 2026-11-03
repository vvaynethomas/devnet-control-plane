import json
import os
from html.parser import HTMLParser
from pathlib import Path
from pathlib import PureWindowsPath
import sqlite3
import tempfile
import shutil
import subprocess
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch

from control_plane.conversation_hub_adapter import (
    local_source_path, read_legacy_sessions, read_local_sessions,
)
from control_plane.handoff import (
    compile_context_handoff, discover_antigravity_sessions, parse_session_turns,
)
from control_plane.fabric import _harvest_antigravity_sessions, _harvest_copilot_sessions
from control_plane.conversations import UnifiedConversationHub
from control_plane.conversation_library import ConversationLibraryError, _configured_hub_api
from control_plane.ui import ControlPlaneWorkbench, _copy_attributes


class ConversationHubAdapterTests(unittest.TestCase):
    def test_copy_controls_preserve_literal_content_without_javascript_interpolation(self) -> None:
        payload = '${globalThis.copyInjected = true} "quoted" \'single\' \\path\\ `tick`\nnext\r\nline & <tag>'

        class CopyButtons(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.buttons = []

            def handle_starttag(self, tag, attrs) -> None:
                attributes = dict(attrs)
                if tag == "button" and "data-copy-text" in attributes:
                    self.buttons.append(attributes)

        parser = CopyButtons()
        parser.feed(f"<button {_copy_attributes(payload)}>Copy</button>")
        self.assertEqual(json.loads(parser.buttons[0]["data-copy-text"]), payload)
        for ordered in (False, True):
            turn = {
                "turn_index": 1, "user_prompt": payload,
                "assistant_responses": [f"```text\n{payload}\n```"],
                "tool_calls": [],
            }
            if ordered:
                turn["messages"] = [
                    {"role": "user", "source_role": "user", "content": payload},
                    {"role": "tool", "source_role": "tool", "content": payload},
                    {"role": "assistant", "source_role": "assistant",
                     "content": turn["assistant_responses"][0]},
                ]
            session = {
                "session_id": "CLI-synthetic", "full_session_id": "synthetic",
                "platform": "GitHub Copilot CLI", "model": "Copilot CLI",
                "title": "Synthetic copy controls", "workspace": "Terminal",
                "created_date": "", "turns": [turn], "turn_count": 1,
                "est_total_tokens": 10, "est_input_tokens": 5, "est_output_tokens": 5,
            }
            result = {
                "sessions": [session],
                "summary": {
                    "total_sessions": 1, "filtered_sessions": 1, "total_turns": 1,
                    "est_total_tokens": 10, "est_input_tokens": 5, "est_output_tokens": 5,
                    "platforms": {"GitHub Copilot CLI": 1}, "models": {"Copilot CLI": 1},
                },
            }
            workbench = ControlPlaneWorkbench.__new__(ControlPlaneWorkbench)
            workbench.factory_root = self.root
            workbench.network_root = self.root
            workbench.conversations_hub = SimpleNamespace(get_all_conversations=lambda **_: result)
            with patch("control_plane.handoff.compile_context_handoff", return_value={"markdown": payload}):
                rendered = workbench.render_conversations_tab()
            rendered_parser = CopyButtons()
            rendered_parser.feed(rendered)
            buttons = rendered_parser.buttons
            self.assertEqual(len(buttons), 5)
            copied = [json.loads(button["data-copy-text"]) for button in buttons]
            self.assertIn(payload, copied)
            self.assertIn(turn["assistant_responses"][0], copied)
            full_turn = (
                "\n\n".join(f"{message['role'].upper()}:\n{message['content']}"
                            for message in turn["messages"])
                if ordered else f"USER:\n{payload}\n\nASSISTANT:\n{turn['assistant_responses'][0]}"
            )
            self.assertIn(full_turn, copied)
            for button in buttons:
                self.assertEqual(button["onclick"],
                                 "copySnippet(JSON.parse(this.dataset.copyText), this)")
            node = shutil.which("node")
            if node:
                script = """
                const fs = require('fs');
                const buttons = JSON.parse(fs.readFileSync(0, 'utf8'));
                const copied = [];
                globalThis.copySnippet = text => copied.push(text);
                for (const attrs of buttons) {
                    new Function(attrs.onclick).call({dataset: {copyText: attrs['data-copy-text']}});
                }
                if (globalThis.copyInjected) throw new Error('Transcript executed');
                process.stdout.write(JSON.stringify(copied));
                """
                execution = subprocess.run(
                    [node, "-e", script], input=json.dumps(buttons), text=True,
                    capture_output=True, check=True,
                )
                self.assertEqual(json.loads(execution.stdout), copied)

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

    def test_imported_odd_token_total_is_preserved_with_and_without_hub(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE imported_chats SET est_tokens = 101")
            connection.commit()
        legacy = UnifiedConversationHub(data_dir=self.root / "odd-legacy")
        legacy.db_path = self.database
        with patch.object(legacy, "_get_hub_api", return_value=None):
            session = legacy.get_imported_chats()[0]
            self.assertEqual(session["est_total_tokens"], 101)
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for odd-total parity")
            raise
        imported, _, _ = read_legacy_sessions(self.database, archive_key="synthetic-odd")
        self.assertEqual(imported[0]["est_total_tokens"], 101)
        self.assertEqual(imported[0]["est_input_tokens"], 50)
        self.assertEqual(imported[0]["est_output_tokens"], 50)

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

    def test_hub_cli_search_and_presentation_preserve_all_message_roles_and_order(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter coverage")
            raise
        path = self.cli_root / "session-b" / "events.jsonl"
        path.write_text("\n".join([
            json.dumps({"message": "orphanneedle synthetic unassigned prelude"}),
            json.dumps({"role": "user", "message": "promptneedle synthetic user content"}),
            json.dumps({"role": "tool", "message": "toolneedle synthetic tool content"}),
            json.dumps({"role": "assistant", "message": "answerneedle synthetic assistant content"}),
        ]) + "\n", encoding="utf-8")
        hub = UnifiedConversationHub(data_dir=self.root / "search-data")
        scan_cli = hub.scan_copilot_cli
        with patch.object(hub, "scan_antigravity", return_value=[]), \
             patch.object(hub, "scan_vscode_copilot", return_value=[]), \
             patch.object(hub, "get_imported_chats", return_value=[]), \
             patch.object(hub, "scan_copilot_cli", side_effect=lambda: scan_cli(self.cli_root)):
            for query in ("orphanneedle", "promptneedle", "toolneedle", "answerneedle"):
                with self.subTest(query=query):
                    result = hub.get_all_conversations(query=query)
                    self.assertEqual(len(result["sessions"]), 1)
            self.assertEqual(hub.get_all_conversations(query="absentneedle")["sessions"], [])
            result = hub.get_all_conversations()
        session = result["sessions"][0]
        self.assertEqual([message["role"] for message in session["messages"]],
                         ["unknown", "user", "tool", "assistant"])
        self.assertEqual(session["unassigned_messages"][0]["role"], "unknown")
        self.assertEqual(session["turns"][0]["other_messages"][0]["role"], "tool")
        self.assertEqual(session["est_total_tokens"],
                         session["est_input_tokens"] + session["est_output_tokens"]
                         + session["est_unclassified_tokens"])
        self.assertGreater(session["est_unclassified_tokens"], 0)
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)):
            body = _harvest_copilot_sessions()[0]["body"]
        words = ("orphanneedle", "promptneedle", "toolneedle", "answerneedle")
        self.assertEqual([body.index(word) for word in words],
                         sorted(body.index(word) for word in words))
        workbench = ControlPlaneWorkbench.__new__(ControlPlaneWorkbench)
        workbench.factory_root = self.root
        workbench.network_root = self.root
        workbench.conversations_hub = SimpleNamespace(get_all_conversations=lambda **_: result)
        with patch("control_plane.handoff.compile_context_handoff", return_value={"markdown": ""}):
            rendered = workbench.render_conversations_tab()
        visible_text = [
            rendered.index(f">{message['content']}</div>")
            for message in session["messages"]
        ]
        self.assertEqual(visible_text, sorted(visible_text))

    def test_hub_unclassified_cli_tokens_title_search_and_summary_are_truthful(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter coverage")
            raise
        synthetic_secret = "ghp_" + "A" * 24
        path = self.cli_root / "session-b" / "events.jsonl"
        path.write_text("\n".join([
            json.dumps({"message": f"unknownneedle synthetic CLI activity {synthetic_secret}"}),
            json.dumps({"role": "tool", "message": "toolneedle synthetic tool-only content"}),
        ]) + "\n", encoding="utf-8")
        hub = UnifiedConversationHub(data_dir=self.root / "unknown-data")
        scan_cli = hub.scan_copilot_cli
        with patch.object(hub, "scan_antigravity", return_value=[]), \
             patch.object(hub, "scan_vscode_copilot", return_value=[]), \
             patch.object(hub, "get_imported_chats", return_value=[]), \
             patch.object(hub, "scan_copilot_cli", side_effect=lambda: scan_cli(self.cli_root)):
            for query in ("unknownneedle", "toolneedle"):
                self.assertEqual(len(hub.get_all_conversations(query=query)["sessions"]), 1)
            self.assertEqual(hub.get_all_conversations(query=synthetic_secret)["sessions"], [])
            result = hub.get_all_conversations()
        session = result["sessions"][0]
        self.assertEqual(session["turns"], [])
        self.assertEqual(session["title"], session["messages"][0]["content"][:90])
        self.assertNotIn(synthetic_secret, session["title"])
        expected = sum(max(1, len(message["content"].strip()) // 4)
                       for message in session["messages"])
        self.assertGreater(expected, 0)
        for value in (session, result["summary"]):
            self.assertEqual(value["est_input_tokens"], 0)
            self.assertEqual(value["est_output_tokens"], 0)
            self.assertEqual(value["est_unclassified_tokens"], expected)
            self.assertEqual(value["est_total_tokens"], expected)
        workbench = ControlPlaneWorkbench.__new__(ControlPlaneWorkbench)
        workbench.factory_root = self.root
        workbench.network_root = self.root
        workbench.conversations_hub = SimpleNamespace(get_all_conversations=lambda **_: result)
        with patch("control_plane.handoff.compile_context_handoff", return_value={"markdown": ""}):
            rendered = workbench.render_conversations_tab()
        self.assertIn(f"Unclassified: ~{expected} (no input/output role)", rendered)
        self.assertIn(f"0 in / 0 out / {expected} unclassified; no input/output role", rendered)
        self.assertNotIn(synthetic_secret, rendered)

    def test_cli_qualifying_message_and_fabric_excerpt_bounds(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for snippet bounds")
            raise
        path = self.cli_root / "session-b" / "events.jsonl"
        events = [{"message": "short"}, {"event": "unsupported"}]
        qualifying = []
        for index in range(15):
            text = f"snippet-{index:02d} " + "x" * 820 + f" beyond800-{index:02d}"
            qualifying.append(text)
            events.append({"role": ("user", "tool", "assistant")[index % 3], "message": f"  {text}  "})
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        hub = UnifiedConversationHub(data_dir=self.root / "snippet-data")
        sessions = hub.scan_copilot_cli(self.cli_root)
        self.assertEqual([message["content"] for message in sessions[0]["messages"]], qualifying[:10])
        self.assertNotIn("snippet-10", json.dumps(sessions))
        self.assertEqual([message["role"] for message in sessions[0]["messages"]],
                         [("user", "tool", "assistant")[index % 3] for index in range(10)])
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
             self.assertLogs("control_plane.fabric", level="WARNING") as captured:
            fabric = _harvest_copilot_sessions()
        self.assertEqual(fabric[0]["body"], "\n\n".join(text[:800] for text in qualifying[:12]))
        self.assertNotIn("beyond800", fabric[0]["body"])
        self.assertNotIn("snippet-12", fabric[0]["body"])
        self.assertTrue(any("800 characters per message" in note for note in captured.output))
        self.assertTrue(any("qualifying messages" in note for note in hub._source_diagnostics))

    def test_cli_title_and_search_exclude_later_prompt_but_totals_cover_window(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for bounded title parity")
            raise
        events = [
            {"role": "tool", "message": f"permitted synthetic tool message {index}"}
            for index in range(10)
        ]
        events.append({"role": "user", "message": "excludedneedle eleventh synthetic user prompt"})
        (self.cli_root / "session-b" / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8",
        )
        hub = UnifiedConversationHub(data_dir=self.root / "bounded-title")
        scan_cli = hub.scan_copilot_cli
        with patch.object(hub, "scan_antigravity", return_value=[]), \
             patch.object(hub, "scan_vscode_copilot", return_value=[]), \
             patch.object(hub, "get_imported_chats", return_value=[]), \
             patch.object(hub, "scan_copilot_cli", side_effect=lambda: scan_cli(self.cli_root)):
            self.assertEqual(hub.get_all_conversations(query="excludedneedle")["sessions"], [])
            result = hub.get_all_conversations()
        session = result["sessions"][0]
        self.assertEqual(session["title"], events[0]["message"])
        self.assertNotIn("excludedneedle", json.dumps(session))
        expected_input = len(events[-1]["message"]) // 4
        expected_other = sum(len(event["message"]) // 4 for event in events[:10])
        self.assertEqual(session["est_input_tokens"], expected_input)
        self.assertEqual(session["est_unclassified_tokens"], expected_other)
        self.assertEqual(session["est_total_tokens"], expected_input + expected_other)
        self.assertEqual(result["summary"]["est_total_tokens"], expected_input + expected_other)
        events = [
            {"role": "user", "message": "permitted synthetic user prompt"},
            *[{"role": "tool", "message": f"permitted synthetic tool message {index}"} for index in range(9)],
            {"role": "assistant", "message": "excluded synthetic assistant",
             "type": "PLANNER_RESPONSE",
             "tool_calls": [{"name": "excludedtoolneedle", "toolSummary": "excludedsummaryneedle"}]},
        ]
        (self.cli_root / "session-b" / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8",
        )
        session = scan_cli(self.cli_root)[0]
        self.assertEqual(session["turns"][0]["tool_calls"], [])
        self.assertNotIn("excludedtoolneedle", json.dumps(session))
        self.assertNotIn("excludedsummaryneedle", json.dumps(session))

    def _write_cli_physical_window_fixture(self) -> None:
        lines = ["\n", json.dumps({"event": "unsupported"}) + "\n"] * 49
        lines.append(json.dumps({"role": "user", "message": "line099 visible synthetic prompt"}) + "\n")
        lines.append(json.dumps({"role": "tool", "message": "line100 visible synthetic tool"}) + "\n")
        lines.append(json.dumps({"role": "assistant", "message": "line101 Fabric-only synthetic answer"}) + "\n")
        lines.extend(["\n"] * 18)
        lines.append(json.dumps({"message": "line120 Fabric boundary synthetic event"}) + "\n")
        lines.append("{malformed beyond both physical windows}\n")
        (self.cli_root / "session-b" / "events.jsonl").write_text("".join(lines), encoding="utf-8")

    def test_no_hub_cli_physical_line_windows_exclude_outside_malformed_content(self) -> None:
        self._write_cli_physical_window_fixture()
        hub = UnifiedConversationHub(data_dir=self.root / "window-legacy")
        with patch.object(hub, "_get_hub_api", return_value=None):
            sessions = hub.scan_copilot_cli(self.cli_root)
        self.assertEqual(len(sessions), 1)
        visible = json.dumps(sessions)
        self.assertIn("line099", visible)
        self.assertIn("line100", visible)
        self.assertNotIn("line101", visible)
        self.assertNotIn("line120", visible)
        unavailable = ConversationLibraryError("hub_unavailable", "optional unavailable", 503)
        with patch("control_plane.conversation_hub_adapter._configured_hub_api", side_effect=unavailable), \
             patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)):
            fabric = _harvest_copilot_sessions()
        self.assertEqual(len(fabric), 1)
        self.assertIn("line101", fabric[0]["body"])
        self.assertIn("line120", fabric[0]["body"])
        self.assertNotIn("malformed", fabric[0]["body"])

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

    @unittest.skipUnless(os.name == "nt", "Windows UNC URI mapping is platform-specific")
    def test_local_source_path_preserves_synthetic_windows_unc_uri(self) -> None:
        expected = Path(r"\\server\share\brain\session%20name\transcript.jsonl")
        uri = expected.as_uri()
        converted = local_source_path(uri)

        self.assertEqual(PureWindowsPath(converted), expected)
        self.assertEqual(converted.anchor, "\\\\server\\share\\")

    def _add_local_path_parity_sources(self) -> dict[str, dict[str, Path]]:
        names = ("session%20literal", "session with space")
        sources: dict[str, dict[str, Path]] = {}
        for name in names:
            ag_path = self.brain_root / name / ".system_generated" / "logs" / "transcript.jsonl"
            ag_path.parent.mkdir(parents=True)
            ag_path.write_text(
                json.dumps({
                    "type": "USER_INPUT",
                    "content": f"<USER_REQUEST>synthetic Antigravity {name}</USER_REQUEST>",
                    "created_at": "2025-01-01T10:00:00Z",
                }) + "\n",
                encoding="utf-8",
            )

            vscode_path = self.vscode_root / "workspace-paths" / "chatSessions" / f"{name}.jsonl"
            vscode_path.parent.mkdir(parents=True, exist_ok=True)
            vscode_path.write_text(
                json.dumps({"v": {"creationDate": 1735725600000, "inputText": f"synthetic VS Code {name}"}})
                + "\n",
                encoding="utf-8",
            )

            cli_path = self.cli_root / name / "events.jsonl"
            cli_path.parent.mkdir(parents=True)
            cli_path.write_text(
                json.dumps({
                    "timestamp": "2025-01-01T10:00:00Z",
                    "role": "user",
                    "message": f"synthetic Copilot CLI path {name} has sufficient content",
                }) + "\n",
                encoding="utf-8",
            )
            sources[name] = {
                "antigravity": ag_path.resolve(),
                "vscode-copilot": vscode_path.resolve(),
                "copilot-cli": cli_path.resolve(),
            }
        return sources

    def _assert_local_path_parity(
        self,
        sources: dict[str, dict[str, Path]],
        *,
        use_hub: bool,
    ) -> None:
        hub = UnifiedConversationHub(data_dir=self.root / f"dncp-data-{use_hub}")
        if not use_hub:
            with patch.object(hub, "_get_hub_api", return_value=None):
                by_kind = {
                    "antigravity": hub.scan_antigravity(self.brain_root),
                    "vscode-copilot": hub.scan_vscode_copilot(self.vscode_root),
                    "copilot-cli": hub.scan_copilot_cli(self.cli_root),
                }
        else:
            by_kind = {
                "antigravity": hub.scan_antigravity(self.brain_root),
                "vscode-copilot": hub.scan_vscode_copilot(self.vscode_root),
                "copilot-cli": hub.scan_copilot_cli(self.cli_root),
            }
        for name, paths_by_kind in sources.items():
            for kind, expected_path in paths_by_kind.items():
                with self.subTest(hub=use_hub, source=kind, path=expected_path):
                    session = next(
                        item for item in by_kind[kind]
                        if item["source_path"] == str(expected_path)
                    )
                    self.assertTrue(Path(session["source_path"]).is_absolute())
                    self.assertTrue(Path(session["source_path"]).is_file())
                    if use_hub:
                        self.assertTrue(session["source_uri"].startswith("file://"))
                        self.assertEqual(local_source_path(session["source_uri"]), expected_path)

    def test_local_source_paths_match_legacy_with_optional_hub(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter integration coverage")
            raise
        sources = self._add_local_path_parity_sources()
        self._assert_local_path_parity(sources, use_hub=True)

    def test_local_source_paths_match_legacy_without_optional_hub(self) -> None:
        sources = self._add_local_path_parity_sources()
        unavailable = ConversationLibraryError("hub_unavailable", "optional package unavailable", 503)
        with patch("control_plane.conversation_hub_adapter._configured_hub_api", side_effect=unavailable):
            self._assert_local_path_parity(sources, use_hub=False)

    def _add_fabric_path_contract_sources(self) -> set[str]:
        names = {"session%20literal", "session with space"}
        for name in names:
            transcript = self.brain_root / name / ".system_generated" / "logs" / "transcript.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                json.dumps({
                    "type": "USER_INPUT",
                    "content": f"<USER_REQUEST>synthetic Antigravity path {name}</USER_REQUEST>",
                    "created_at": "2025-01-01T10:00:00Z",
                }) + "\n",
                encoding="utf-8",
            )
            cli_events = self.cli_root / name / "events.jsonl"
            cli_events.parent.mkdir(parents=True)
            cli_events.write_text(
                json.dumps({
                    "timestamp": "2025-01-01T10:00:00Z",
                    "role": "user",
                    "message": f"synthetic Copilot path {name} has sufficiently long content",
                }) + "\n",
                encoding="utf-8",
            )
        return names

    def _assert_fabric_absolute_paths_exist(self, names: set[str]) -> None:
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)):
            antigravity = _harvest_antigravity_sessions()
            copilot = _harvest_copilot_sessions()
        ag_paths = {
            Path(record["abs_path"]).parents[2].name: record
            for record in antigravity
            if Path(record["abs_path"]).parents[2].name in names
        }
        cli_paths = {
            Path(record["abs_path"]).parent.name: record
            for record in copilot
            if Path(record["abs_path"]).parent.name in names
        }
        self.assertEqual(set(ag_paths), names)
        self.assertEqual(set(cli_paths), names)
        for name in names:
            with self.subTest(source="Antigravity", session=name):
                path = Path(ag_paths[name]["abs_path"])
                self.assertTrue(path.is_absolute())
                self.assertTrue(path.is_file())
            with self.subTest(source="Copilot CLI", session=name):
                path = Path(cli_paths[name]["abs_path"])
                self.assertTrue(path.is_absolute())
                self.assertTrue(path.is_file())
                self.assertEqual(cli_paths[name]["path"], str(path))

    def test_fabric_abs_paths_are_filesystem_paths_with_hub(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for source-adapter integration coverage")
            raise
        names = self._add_fabric_path_contract_sources()
        self._assert_fabric_absolute_paths_exist(names)

    def test_fabric_abs_paths_are_filesystem_paths_without_hub(self) -> None:
        names = self._add_fabric_path_contract_sources()
        unavailable = ConversationLibraryError("hub_unavailable", "optional package unavailable", 503)
        with patch("control_plane.conversation_hub_adapter._configured_hub_api", side_effect=unavailable):
            self._assert_fabric_absolute_paths_exist(names)

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

    def _assert_direct_handoff_reads_exact_path(self) -> None:
        outside_layout = self.root / "selected%20 file.jsonl"
        outside_cap = self.brain_root / "old-session" / ".system_generated" / "logs" / "transcript.jsonl"
        outside_cap.parent.mkdir(parents=True)
        for index in range(21):
            directory = self.brain_root / f"new-session-{index}"
            directory.mkdir()
            os.utime(directory, (1_800_000_000 + index, 1_800_000_000 + index))
        os.utime(outside_cap.parents[2], (1_600_000_000, 1_600_000_000))
        events = "\n".join([
            "{malformed synthetic line}",
            json.dumps({"type": "USER_INPUT", "content": "synthetic selected prompt"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "synthetic selected answer"}),
        ]) + "\n"
        outside_layout.write_text(events, encoding="utf-8")
        outside_cap.write_text(events, encoding="utf-8")
        for path in (outside_layout, outside_cap):
            with self.subTest(path=path):
                before = path.read_bytes()
                turns = parse_session_turns(path)
                self.assertEqual(turns[0]["user_prompt"], "synthetic selected prompt")
                self.assertEqual(turns[0]["assistant_responses"], ["synthetic selected answer"])
                self.assertEqual(path.read_bytes(), before)

    def test_direct_handoff_without_hub_reads_exact_path_and_skips_bad_lines(self) -> None:
        unavailable = ConversationLibraryError("hub_unavailable", "optional package unavailable", 503)
        with patch("control_plane.handoff._configured_hub_api", side_effect=unavailable):
            self._assert_direct_handoff_reads_exact_path()

    def test_direct_handoff_with_hub_reads_exact_path_and_skips_bad_lines(self) -> None:
        try:
            _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for exact-file coverage")
            raise
        with self.assertLogs("control_plane.handoff", level="WARNING") as captured:
            self._assert_direct_handoff_reads_exact_path()
        self.assertTrue(any("malformed line(s) skipped" in item for item in captured.output))

    def test_direct_handoff_incompatible_hub_fails_closed_before_layout_check(self) -> None:
        path = self.root / "off-layout.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        incompatible = ConversationLibraryError("hub_incompatible", "wrong installed commit", 503)
        with patch("control_plane.handoff._configured_hub_api", side_effect=incompatible):
            with self.assertRaises(ConversationLibraryError):
                parse_session_turns(path)

    def test_malformed_siblings_are_isolated_across_all_migrated_consumers(self) -> None:
        try:
            api, _ = _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for contract coverage")
            raise
        bad_ag = self.brain_root / "bad-session" / ".system_generated" / "logs" / "transcript.jsonl"
        bad_vscode = self.vscode_root / "workspace-a" / "chatSessions" / "bad.jsonl"
        bad_cli = self.cli_root / "bad-session" / "events.jsonl"
        for path in (bad_ag, bad_vscode, bad_cli):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{malformed synthetic file}\n", encoding="utf-8")
        for kind, root in (
            ("antigravity", self.brain_root),
            ("vscode-copilot", self.vscode_root),
            ("copilot-cli", self.cli_root),
        ):
            with self.subTest(source=kind):
                reader = getattr(api, {
                    "antigravity": "read_antigravity_sessions",
                    "vscode-copilot": "read_vscode_copilot_sessions",
                    "copilot-cli": "read_copilot_cli_sessions",
                }[kind])
                with self.assertRaises(ValueError):
                    reader(root, archive_key="strict-contract", max_sessions=25)
                sessions, diagnostics, _ = read_local_sessions(
                    kind, root, archive_key="synthetic-contract", max_sessions=25,
                    selection_policy="directory-first" if kind == "antigravity" else None,
                )
                self.assertEqual(len(sessions), 1)
                self.assertTrue(any("1 malformed selected source files skipped" in note for note in diagnostics))
                self.assertFalse(any("{malformed synthetic file}" in note for note in diagnostics))
        manager = UnifiedConversationHub(data_dir=self.root / "hub-compatibility")
        self.assertEqual(len(manager.scan_antigravity(self.brain_root)), 1)
        self.assertEqual(len(manager.scan_vscode_copilot(self.vscode_root)), 1)
        self.assertEqual(len(manager.scan_copilot_cli(self.cli_root)), 1)
        self.assertTrue(any("malformed selected source files skipped" in note
                            for note in manager._source_diagnostics))
        with patch("control_plane.fabric.os.path.expanduser", return_value=str(self.home)), \
             patch("control_plane.handoff.os.path.expanduser", return_value=str(self.home)):
            self.assertEqual(len(_harvest_antigravity_sessions()), 1)
            self.assertEqual(len(_harvest_copilot_sessions()), 1)
            self.assertEqual(len(discover_antigravity_sessions()), 1)
        legacy = UnifiedConversationHub(data_dir=self.root / "legacy-compatibility")
        with patch.object(legacy, "_get_hub_api", return_value=None):
            self.assertEqual(len(legacy.scan_antigravity(self.brain_root)), 1)
            self.assertEqual(len(legacy.scan_vscode_copilot(self.vscode_root)), 1)
            self.assertEqual(len(legacy.scan_copilot_cli(self.cli_root)), 1)

    def test_incompatible_installed_hub_does_not_fall_back(self) -> None:
        hub = UnifiedConversationHub(data_dir=self.root / "dncp-data")
        incompatible = ConversationLibraryError(
            "hub_incompatible", "wrong installed commit", 503,
        )
        with patch("control_plane.conversations._configured_hub_api", side_effect=incompatible):
            with self.assertRaises(ConversationLibraryError):
                hub.scan_antigravity(self.brain_root)

    def test_tolerant_source_reads_keep_caps_and_resource_failures_fatal(self) -> None:
        try:
            api, info = _configured_hub_api()
        except ConversationLibraryError as exc:
            if exc.code == "hub_unavailable":
                self.skipTest("Install the optional Conversation Hub extra for bound coverage")
            raise
        bad_ag = self.brain_root / "new-bad" / ".system_generated" / "logs" / "transcript.jsonl"
        bad_vscode = self.vscode_root / "workspace-a" / "chatSessions" / "new-bad.jsonl"
        bad_cli = self.cli_root / "new-bad" / "events.jsonl"
        for path in (bad_ag, bad_vscode, bad_cli):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{malformed synthetic}\n", encoding="utf-8")
            os.utime(path, (1_900_000_000, 1_900_000_000))
        os.utime(bad_ag.parents[2], (1_900_000_000, 1_900_000_000))
        with patch("control_plane.conversation_hub_adapter._configured_hub_api", return_value=(api, info)):
            for kind, root in (
                ("antigravity", self.brain_root),
                ("vscode-copilot", self.vscode_root),
                ("copilot-cli", self.cli_root),
            ):
                with self.subTest(source=kind):
                    selected, diagnostics, _ = read_local_sessions(
                        kind, root, archive_key="no-refill", max_sessions=1,
                        selection_policy="directory-first" if kind == "antigravity" else None,
                    )
                    self.assertEqual(selected, [])
                    self.assertTrue(any("1 selected slots; no cap refill" in note for note in diagnostics))
                    source_globals = api.read_antigravity_sessions.__globals__
                    for limit, value in (
                        ("MAX_SOURCE_FILE_BYTES", 8),
                        ("MAX_SOURCE_ROOT_BYTES", 8),
                        ("MAX_EVENTS_PER_SESSION", 1),
                    ):
                        with self.subTest(limit=limit), patch.dict(source_globals, {limit: value}):
                            with self.assertRaises(ValueError):
                                read_local_sessions(kind, root, archive_key="fatal-bound", max_sessions=25)
            transcript = self.session_dir / ".system_generated" / "logs" / "transcript.jsonl"
            with patch.dict(api.read_antigravity_transcript.__globals__, {"MAX_SOURCE_FILE_BYTES": 8}), \
                 patch("control_plane.handoff._configured_hub_api", return_value=(api, info)), \
                 self.assertLogs("control_plane.handoff", level="WARNING") as captured:
                self.assertEqual(parse_session_turns(transcript), [])
            self.assertTrue(any("could not read" in note for note in captured.output))

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
                "version": "0.1.5",
                "revision": "cd66bd37ebad82c28465270a915415df1aacec3e",
                "diagnostics": ["<source> is bounded"],
            },
        })
        with patch(
            "control_plane.handoff.compile_context_handoff",
            return_value={"markdown": "synthetic handoff"},
        ):
            rendered = workbench.render_conversations_tab()

        self.assertIn("conversation-hub 0.1.5", rendered)
        self.assertIn("cd66bd37ebad82c28465270a915415df1aacec3e", rendered)
        self.assertIn("&lt;source&gt; is bounded", rendered)
        self.assertIn("&lt;tool&gt; output", rendered)
        self.assertIn("&lt;unassigned&gt; source", rendered)


if __name__ == "__main__":
    unittest.main()
