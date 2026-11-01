"""Portable decision-aid tests; no personal transcripts, cloud calls or external Factory."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from control_plane.decision_aid import DECISION_TOPICS, build_decision_aid
from control_plane.fabric import collect_knowledge_entities
from control_plane.ui import ControlPlaneWorkbench, make_handler


class TestDecisionAid(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.factory = self.root / "incubator"
        self.factory.mkdir()
        self.paths = {}
        self.write_record(
            "SRC-9876", "source", [], [], "Source hypothesis, not accepted deployment advice.",
        )
        for index, topic in enumerate(DECISION_TOPICS):
            self.write_record(
                f"PAT-{9870 + index}", "pattern", [topic], ["SRC-9876", "FND-9999"],
                f"Guidance for {topic}: compare alternatives; retain uncertainty. <script>bad()</script>",
            )

    def write_record(
        self, record_id: str, kind: str, tags: list[str],
        upstream: list[str], body: str, status: str = "provisional",
    ) -> None:
        folder = self.factory / "knowledge" / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{record_id}.md"
        path.write_text(
            "---\n"
            f'id: "{record_id}"\ntitle: "Fixture {record_id}"\ntype: "{kind}"\n'
            f'status: "{status}"\ncreated_date: "2026-11-01"\n'
            f"tags: {json.dumps(tags)}\nupstream_refs: {json.dumps(upstream)}\n"
            "downstream_refs: []\n---\n" + body,
            encoding="utf-8",
        )
        self.paths[record_id] = path

    def workbench(self) -> ControlPlaneWorkbench:
        wb = ControlPlaneWorkbench(
            factory_root=self.factory, network_root=self.root, data_dir=self.root / "runtime",
        )
        wb.fabric.rebuild(include_conversations=False)
        return wb

    def test_each_topic_selects_only_tagged_canonical_records(self) -> None:
        for index, topic in enumerate(DECISION_TOPICS):
            with self.subTest(topic=topic):
                aid = build_decision_aid(self.factory, topic, "Needs persistent service; budget unknown.")
                self.assertEqual([r["id"] for r in aid["records"]], [f"PAT-{9870 + index}"])
                self.assertEqual(aid["operator_context"], "Needs persistent service; budget unknown.")
                self.assertEqual(aid["mode"], "read-only-advisory")
                record = aid["records"][0]
                self.assertEqual(record["status"], "provisional")
                self.assertTrue(record["upstream_refs"][0]["resolved"])
                self.assertEqual(record["upstream_refs"][0]["status"], "provisional")
                self.assertFalse(record["upstream_refs"][1]["resolved"])
                self.assertEqual(record["upstream_refs"][1]["status"], "unknown")
                self.assertNotIn("score", aid)
                self.assertIn("No provider is selected", aid["uncertainty"])
                self.assertGreaterEqual(len(aid["alternatives"]), 2)

    def test_current_records_are_not_copied_or_persisted(self) -> None:
        before = {p.relative_to(self.factory): p.read_bytes() for p in self.factory.rglob("*.md")}
        build_decision_aid(self.factory)
        self.assertEqual(before, {
            p.relative_to(self.factory): p.read_bytes() for p in self.factory.rglob("*.md")
        })
        self.paths["PAT-9870"].write_text(
            self.paths["PAT-9870"].read_text(encoding="utf-8") + "\nRevised canonical alternative.",
            encoding="utf-8",
        )
        self.assertIn("Revised canonical alternative", build_decision_aid(self.factory)["records"][0]["body"])
        self.assertFalse(list(self.factory.rglob("*.sqlite")))
        self.paths["PAT-9870"].unlink()
        self.assertEqual(build_decision_aid(self.factory)["records"], [])

    def test_active_and_draft_records_do_not_imply_approval(self) -> None:
        self.write_record(
            "FND-9873", "finding", ["capability-routing"], ["SRC-9876"],
            "An active finding records a hypothesis, not a verified capability.", status="active",
        )
        self.write_record(
            "PAT-9872", "pattern", ["capability-routing"], ["FND-9873"],
            "A draft pattern requires evaluation and manual override.", status="draft",
        )
        aid = build_decision_aid(self.factory, "capability-routing")
        self.assertEqual({r["status"] for r in aid["records"]}, {"active", "draft"})
        self.assertIn("not verified approval", aid["uncertainty"])
        self.assertTrue(all(ref["resolved"] for r in aid["records"] for ref in r["upstream_refs"]))
        html = self.workbench().render_decision_aid("capability-routing")
        self.assertIn("badge-neutral\">active", html)
        self.assertIn("badge-neutral\">draft", html)
        self.assertIn("not verified approval", html)

    def test_fabric_and_existing_discovery_remain_usable(self) -> None:
        entities = collect_knowledge_entities(self.factory)
        self.assertEqual(entities["PAT-9870"]["tags"], ["infrastructure-decision"])
        wb = self.workbench()
        results = wb.fabric.search("infrastructure-decision")
        self.assertIn("PAT-9870", [record["id"] for record in results["results"]])
        html = wb.render_capabilities_tab("Guidance", "capability-routing", "Context unknown")
        self.assertIn("Decision Aid", html)
        self.assertIn("Capability Discovery", html)
        self.assertIn("What Patterns Are Related?", html)
        self.assertIn('name="prob" value="Guidance"', html)
        self.assertIn('name="aid_context" value="Context unknown"', html)

    def test_ui_exposes_uncertainty_provenance_and_escapes_content(self) -> None:
        html = self.workbench().render_decision_aid(
            operator_context="<script>operator()</script>",
        )
        self.assertIn("provisional", html)
        self.assertIn("not verified", html)
        self.assertIn("Unresolved canonical reference", html)
        self.assertIn("entity=SRC-9876", html)
        self.assertIn("knowledge/pattern/PAT-9870.md", html)
        self.assertIn("Alternatives to compare (not ranked)", html)
        self.assertNotIn("<script>bad()", html)
        self.assertNotIn("<script>operator()", html)
        self.assertIn("&lt;script&gt;bad()", html)
        self.assertIn("browser history", html)

    def test_missing_records_invalid_topic_and_read_error_are_explicit(self) -> None:
        self.paths["PAT-9870"].unlink()
        wb = self.workbench()
        self.assertIn("No canonical records", wb.render_decision_aid())
        with self.assertRaisesRegex(ValueError, "Unknown decision topic"):
            build_decision_aid(self.factory, "unregistered-topic")
        with self.assertRaisesRegex(FileNotFoundError, "incubator directory"):
            build_decision_aid(self.root / "missing-incubator")
        self.assertIn('role="alert"', wb.render_decision_aid("unregistered-topic"))
        with patch("control_plane.decision_aid.collect_knowledge_entities", side_effect=OSError("fixture read denied")):
            self.assertIn("fixture read denied", wb.render_decision_aid())

    def test_escaping_record_path_is_rejected(self) -> None:
        entity = collect_knowledge_entities(self.factory)["PAT-9870"]
        entity["abs_path"] = str(self.root / "outside.md")
        with patch("control_plane.decision_aid.collect_knowledge_entities", return_value={entity["id"]: entity}):
            with self.assertRaisesRegex(ValueError, "outside the configured incubator"):
                build_decision_aid(self.factory)

    def test_http_api_and_page_are_read_only_with_explicit_errors(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.workbench()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/api/decision-aid?topic=capability-routing&context=local-only", timeout=5) as response:
                aid = json.load(response)
            self.assertEqual(aid["topic"], "capability-routing")
            self.assertEqual(aid["operator_context"], "local-only")
            with urllib.request.urlopen(base + "/?tab=capabilities&aid_topic=coordination-recoverability", timeout=5) as response:
                self.assertIn("Fixture PAT-9871", response.read().decode("utf-8"))
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/api/decision-aid?topic=bad", timeout=5)
            self.assertEqual(error.exception.code, 400)
            self.assertIn("Unknown decision topic", json.load(error.exception)["error"])
            error.exception.close()
            with patch("control_plane.decision_aid.collect_knowledge_entities", side_effect=OSError("fixture read denied")):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + "/api/decision-aid", timeout=5)
                self.assertEqual(error.exception.code, 500)
                self.assertIn("fixture read denied", json.load(error.exception)["error"])
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
