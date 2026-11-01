"""Portable phone-home contracts; no personal transcripts or network services."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from control_plane.cli import main
from control_plane.phone_home import MAX_REQUEST_BYTES, PhoneHome, PhoneHomeError, validate_submission
from control_plane.ui import ControlPlaneWorkbench, make_handler, serve_control_plane


class TestPhoneHome(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.factory = self.root / "incubator"
        self.network = self.root / "network"
        self.data = self.root / "runtime"
        self.factory.mkdir()
        self.network.mkdir()
        cockpit = self.factory / "cockpit"
        cockpit.mkdir()
        for kind in ("skill", "prompt", "runbook", "project"):
            entries = []
            if kind in ("skill", "runbook"):
                entries = [{"id": "SKL-9876" if kind == "skill" else "RUN-9876",
                            "title": "SQLite reuse tool", "path": "tools.md",
                            "input_schema": "sqlite", "output_schema": "reuse", "status": "provisional"}]
            if kind == "project":
                entries = [{"id": "PRJ-9876", "title": "Fixture owner product", "path": "projects/fixture"}]
            (cockpit / f"{kind}-registry.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
        (self.factory / "tools.md").write_text("SQLite tool", encoding="utf-8")
        for rid, kind in (("FND-9876", "finding"), ("DEC-9876", "decision"), ("PAT-9876", "pattern")):
            folder = self.factory / "knowledge" / ("patterns" if kind == "pattern" else kind)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{rid}.md").write_text(
                f'---\nid: "{rid}"\ntitle: "SQLite fixture"\ntype: "{kind}"\nstatus: "draft"\n'
                'created_date: "2026-11-01"\ntags: [capability-routing]\nupstream_refs: [SRC-9999]\n'
                'downstream_refs: []\n---\nSQLite search reuse fixture', encoding="utf-8",
            )
        repo = self.network / "fixture"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "tool.py").write_text('"""SQLite reusable fixture."""\ndef search_sqlite(): pass\n', encoding="utf-8")
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "ignored.py").write_text('"""sqlite ignored"""', encoding="utf-8")
        self.service = PhoneHome(self.factory, self.network, self.data)
        self.payload = {"kind": "tool", "title": "SQLite discovery", "summary": "<script>not executed</script>",
                        "source_repo": "fixture", "reuse_query": "sqlite", "related_refs": ["FND-9876"],
                        "external_evidence": "Component evaluation pending; source reference is unverified."}

    def source_snapshot(self) -> dict[str, bytes]:
        return {str(p): p.read_bytes() for root in (self.factory, self.network) for p in root.rglob("*") if p.is_file()}

    def test_check_inventory_provenance_ladder_and_read_only(self) -> None:
        before = self.source_snapshot()
        with patch("control_plane.fabric._harvest_antigravity_sessions", side_effect=AssertionError("personal read")), \
             patch("control_plane.fabric._harvest_copilot_sessions", side_effect=AssertionError("personal read")):
            result = self.service.check("sqlite")
        ids = {r["id"] for r in result["existing_tools_and_modules"]}
        self.assertIn("SKL-9876", ids)
        self.assertIn("RUN-9876", ids)
        self.assertIn("MOD:fixture:tool.py", ids)
        self.assertEqual(next(t for t in result["existing_tools_and_modules"] if t["id"] == "RUN-9876")["status"], "provisional")
        self.assertFalse(any("ignored" in x for x in ids))
        self.assertEqual(result["related_patterns"][0]["id"], "PAT-9876")
        self.assertIn("DEC-9876", {r["id"] for r in result["prior_findings_and_decisions"]})
        self.assertEqual(result["decision_ladder"]["stopped_at"], 1)
        self.assertEqual([s["step"] for s in result["decision_ladder"]["steps"]], [1, 2, 3, 4])
        self.assertTrue(result["decision_ladder"]["human_final_choice"])
        self.assertFalse(result["coverage"]["fabric"]["includes_conversations"])
        self.assertTrue(result["coverage"]["fabric"]["rebuilt_at"])
        self.service.submit(self.payload)
        self.assertEqual(before, self.source_snapshot())
        self.assertEqual(self.service.check("sqlite")["provisional_intake"]["total"], 1)

    def test_unknown_steps_not_skipped_or_fabricated(self) -> None:
        result = self.service.check("unmatchablezzzz98766")
        ladder = result["decision_ladder"]
        self.assertEqual(ladder["stopped_at"], 2)
        self.assertEqual(ladder["steps"][1]["status"], "unresolved")
        self.assertEqual(ladder["steps"][2]["candidate_owners"][0]["id"], "PRJ-9876")
        self.assertIn("not recommended", ladder["steps"][3]["status"])
        self.assertNotIn("external_candidates", ladder)
        self.assertEqual(ladder["steps"][1]["external_check"], "external check not performed")
        self.service.submit({**self.payload, "reuse_query": "unmatchablezzzz98766"})
        self.assertEqual(self.service.check("unmatchablezzzz98766")["decision_ladder"]["stopped_at"], 2)

    def test_persistence_idempotency_and_concurrent_append(self) -> None:
        payload = {**self.payload, "idempotency_key": "test-key"}
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.service.submit(payload), range(8)))
        self.assertEqual(len({r["id"] for r in receipts}), 1)
        self.assertEqual(receipts[0]["status"], "provisional")
        self.assertTrue(receipts[0]["id"].startswith("INTAKE-"))
        self.assertEqual(self.service.list()["total"], 1)
        reopened = PhoneHome(self.factory, self.network, self.data)
        self.assertEqual(reopened.get(receipts[0]["id"]), receipts[0])
        with self.assertRaises(PhoneHomeError) as error:
            self.service.submit({**payload, "summary": "changed"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.service.list()["total"], 1)

    def test_exact_validation_bounds_and_no_failed_persistence(self) -> None:
        clean = validate_submission({**self.payload, "title": "t" * 200, "summary": "x" * 20000,
                                     "reuse_query": "q" * 2000, "tags": ["t"] * 20})
        self.assertEqual(len(clean["summary"]), 20000)
        invalid = [{"title": "x" * 201}, {"summary": "x" * 20001}, {"reuse_query": "q" * 2001},
                   {"tags": ["x"] * 21}, {"tags": "x"}, {"kind": "canonical"}, {"schema_version": True},
                   {"schema_version": 2}, {"status": "approved"}, {"summary": ""}, {"source_repo": 3},
                   {"title": "ghp_" + "a" * 30}, {"summary": "\U0001f600" * 20000}]
        for change in invalid:
            with self.subTest(change=list(change)):
                with self.assertRaises(PhoneHomeError):
                    self.service.submit({**self.payload, **change})
        self.assertEqual(self.service.list()["total"], 0)
        for limit in (0, 51, True, "20"):
            with self.assertRaises(PhoneHomeError):
                self.service.check("sqlite", limit)
        self.assertEqual(self.service.list(limit=50)["submissions"], [])
        with self.assertRaises(PhoneHomeError):
            PhoneHome(self.factory, self.network, self.factory / "runtime")

    def test_unavailable_sources_invalid_registry_and_legacy_freshness(self) -> None:
        missing = PhoneHome(self.root / "missing", self.root / "missing-network", self.root / "other-runtime")
        result = missing.check("sqlite")
        self.assertFalse(result["coverage"]["canonical_available"])
        self.assertFalse(result["coverage"]["fabric"]["built"])
        (self.factory / "cockpit" / "project-registry.json").write_text("{", encoding="utf-8")
        self.assertTrue(any("invalid" in w for w in self.service.check("sqlite")["warnings"]))
        self.service.fabric.rebuild(include_conversations=False)
        with closing(sqlite3.connect(self.service.fabric.db_path)) as conn:
            conn.execute("DROP TABLE fabric_metadata")
            conn.commit()
        self.assertIsNone(self.service.fabric.freshness()["rebuilt_at"])

    def test_malformed_sources_report_partial_and_wrong_root_is_explicit(self) -> None:
        registry = self.factory / "cockpit" / "skill-registry.json"
        registry.write_text(json.dumps({"entries": [{"id": "SKL-9999", "title": 42, "path": 8}]}), encoding="utf-8")
        result = self.service.check("sqlite")
        self.assertFalse(result["coverage"]["canonical_available"])
        self.assertTrue(any("read failed" in warning for warning in result["warnings"]))
        registry.write_text('{"entries":[]}', encoding="utf-8")
        self.service.fabric.rebuild(include_conversations=False)
        other = self.root / "other-incubator"
        other.mkdir()
        service = PhoneHome(other, self.network, self.data)
        with self.assertRaisesRegex(PhoneHomeError, "another canonical root"):
            service.check("sqlite")

    def test_cli_parity_errors_and_export(self) -> None:
        args = ["--factory-root", str(self.factory), "--network-root", str(self.network), "--data-dir", str(self.data)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["phone-home", "check", "sqlite", "--json"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["decision_ladder"], self.service.check("sqlite")["decision_ladder"])
        report = self.root / "report.json"
        report.write_text(json.dumps(self.payload), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["phone-home", "submit", "--file", str(report)]), 0)
        receipt = json.loads(output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["phone-home", "intake", "export", receipt["id"]]), 0)
        self.assertEqual(json.loads(output.getvalue()), self.service.get(receipt["id"]))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["phone-home", "check", ""]), 1)

    def server(self) -> tuple[ControlPlaneWorkbench, str]:
        wb = ControlPlaneWorkbench(self.factory, self.network, self.data)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(wb))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return wb, f"http://127.0.0.1:{server.server_port}"

    def test_http_ui_parity_and_security_boundaries(self) -> None:
        wb, base = self.server()
        with urllib.request.urlopen(base + "/api/phone-home/check?q=sqlite") as res:
            data = json.load(res)
        self.assertEqual(data["decision_ladder"], self.service.check("sqlite")["decision_ladder"])
        req = urllib.request.Request(base + "/api/phone-home/submissions", json.dumps(self.payload).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 201)
            receipt = json.load(res)
        self.assertEqual(receipt, self.service.get(receipt["id"]))
        with urllib.request.urlopen(base + "/?tab=capabilities&prob=sqlite") as res:
            html = res.read().decode()
        self.assertIn("Decision Aid", html)
        self.assertIn("reuse/customize", html)
        self.assertNotIn("<script>not executed</script>", html)
        self.assertIn("&lt;script&gt;", html)
        for headers, raw, path, status in [
            ({"Content-Type": "application/json", "Origin": "https://attacker.test"}, b"{}", "/api/phone-home/submissions", 403),
            ({"Content-Type": "application/json", "Host": "attacker.test"}, b"{}", "/api/phone-home/submissions", 403),
            ({"Content-Type": "application/json"}, b"{", "/api/phone-home/submissions", 400),
            ({"Content-Type": "application/json"}, b"x" * (MAX_REQUEST_BYTES + 1), "/api/phone-home/submissions", 413),
            ({"Content-Type": "application/x-www-form-urlencoded"}, b"csrf=bad", "/action/phone-home-submit", 403),
        ]:
            with self.subTest(status=status, path=path):
                req = urllib.request.Request(base + path, raw, headers, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(req)
                self.assertEqual(error.exception.code, status)
                error.exception.close()
        form = {**self.payload, "related_refs": "FND-9876", "csrf": wb.phone_home_csrf}
        req = urllib.request.Request(base + "/action/phone-home-submit", urllib.parse.urlencode(form).encode(),
                                     {"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(req) as res:
            self.assertIn("provisional intake", res.read().decode())
        self.assertEqual(self.service.list()["total"], 2)

    def test_safe_startup_no_live_evaluation_or_chat_harvest(self) -> None:
        wb = ControlPlaneWorkbench(self.factory, self.network, self.data)
        with patch.object(wb.interaction_lab, "run_side_by_side_evaluation", side_effect=AssertionError("live call")), \
             patch("control_plane.fabric._harvest_antigravity_sessions", side_effect=AssertionError("chat read")):
            server = serve_control_plane(port=0, workbench=wb)
            server.server_close()
        with self.assertRaises(ValueError):
            serve_control_plane(host="0.0.0.0", workbench=wb)

    def test_existing_compiler_and_paste_import_with_fixture_scanners(self) -> None:
        import test_control_plane as existing
        from control_plane.conversations import UnifiedConversationHub
        suite = unittest.TestSuite(existing.TestControlPlaneMVP(name) for name in (
            "test_pillar5_interaction_frame_compiler_and_lab_evaluation",
            "test_pillar6_conversations_command_center_and_tokenomics",
        ))
        with patch.object(existing, "FACTORY_ROOT", self.factory), \
             patch.object(existing, "DEV_NETWORK_ROOT", self.network), \
             patch.object(UnifiedConversationHub, "scan_antigravity", return_value=[]), \
             patch.object(UnifiedConversationHub, "scan_vscode_copilot", return_value=[]), \
             patch.object(UnifiedConversationHub, "scan_copilot_cli", return_value=[]), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            result = unittest.TestResult()
            suite.run(result)
        self.assertTrue(result.wasSuccessful(), str(result.errors) + str(result.failures))


if __name__ == "__main__":
    unittest.main()
