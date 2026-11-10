"""Synthetic coverage for read-only handoff preparation with retrieved references."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from control_plane import hub_index
from control_plane.fabric import FabricIndex
from control_plane.phone_home import PhoneHome, PhoneHomeError


def packet(handoff_id: str, scope: list[str], action: str, **extra) -> dict:
    return {
        "handoff_id": handoff_id, "mode": "request", "sender": "synthetic-sender",
        "recipient": "synthetic-recipient", "scope": scope, "context_snapshot": "Synthetic context.",
        "requested_action": action, "blockers": [], "source_refs": [], **extra,
    }


class HandoffPrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.factory = self.root / "factory"
        (self.factory / "knowledge").mkdir(parents=True)
        self.service = PhoneHome(self.factory, self.root / "network", self.root / "runtime")
        self.fabric: FabricIndex = self.service.fabric

    def add_record(self, record_id: str, title: str, body: str) -> None:
        (self.factory / "knowledge" / f"{record_id}.md").write_text(
            f"---\nid: {record_id}\ntitle: {title}\ntype: finding\n---\n{body}\n", encoding="utf-8")

    def add_conversations(self, rows: list[tuple[str, str, str, int, str]]) -> None:
        """Write Hub index rows directly: (name, title, body, title_is_derived, updated_at)."""
        self.fabric.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.fabric.db_path)) as conn:
            hub_index.ensure_schema(conn)
            for name, title, body, derived, updated in rows:
                cid, revision = (name * 64)[:64], (name[::-1] * 64)[:64]
                conn.execute("INSERT INTO hub_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (cid, revision, "synthetic-cli", title, derived, updated, updated, 4, 1))
                conn.execute("INSERT INTO hub_chunks_fts VALUES (?, ?, ?, ?, ?, ?)",
                             (cid, revision, 2, 3, title, body))
            conn.commit()

    def test_draft_cites_all_three_sources_without_copying_text(self) -> None:
        self.add_record("FND-9001", "Lemur migration finding", "The lemur migration needs a dry run.")
        self.fabric.rebuild(include_conversations=False)
        self.add_conversations([
            ("ab", "Lemur planning", "user: PRIVATE-BODY lemur migration notes", 0, "2026-02-01T00:00:00Z"),
            ("cd", "PRIVATE-DERIVED lemur", "user: PRIVATE-BODY lemur again", 1, "2026-01-01T00:00:00Z"),
        ])
        stored = self.service.handoff_submit(packet("earlier-1", ["zoo-product"], "Run the lemur migration."))
        self.service.handoff_result({
            "result_id": "r1", "handoff_id": "earlier-1", "responder": "synthetic-recipient",
            "outcome": "blocked", "summary": "Blocked.", "blockers": ["No dry run."], "source_refs": []})
        before = self.service.list()["total"]
        own = {"ref": "urn:synthetic:mine", "revision": None}
        with patch("urllib.request.urlopen", side_effect=AssertionError("no fetch")), \
             patch("subprocess.run", side_effect=AssertionError("no execution")), \
             patch.object(FabricIndex, "rebuild", side_effect=AssertionError("no build")):
            result = self.service.handoff_prepare({
                "scope": ["zoo-product"], "requested_action": "Plan the lemur migration for the zoo",
                "context_snapshot": "Synthetic snapshot.", "source_refs": [own]})
        self.assertEqual(self.service.list()["total"], before)
        self.assertEqual(result["mode"], "read-only-handoff-preparation")
        self.assertEqual(result["search_terms"], ["plan", "lemur", "migration", "zoo", "zoo-product"])
        draft = result["draft"]
        self.assertEqual(draft["source_refs"][0], own)
        self.assertEqual(draft["source_refs"][1],
                         {"ref": "handoff:earlier-1", "revision": "sha256:" + stored["content_digest"]})
        self.assertEqual(draft["source_refs"][2], {"ref": "FND-9001", "revision": None})
        hub_refs = [ref for ref in draft["source_refs"] if ref["ref"].startswith("conversation-hub://")]
        self.assertEqual(len(hub_refs), 2)
        self.assertRegex(hub_refs[0]["ref"], r"^conversation-hub://[0-9a-z]{64}/[0-9a-z]{64}#message=2$")
        self.assertEqual(hub_refs[0]["revision"], hub_refs[0]["ref"].split("/")[3].split("#")[0])
        self.assertEqual(result["missing_fields"], ["handoff_id", "mode", "sender", "recipient"])
        self.assertEqual(result["references_omitted"], 0)
        by_source = {}
        for match in result["matches"]:
            by_source.setdefault(match["source"], []).append(match)
        self.assertEqual(by_source["handoff"][0]["state"], "blocked")
        self.assertEqual(by_source["handoff"][0]["shared_scope"], ["zoo-product"])
        self.assertEqual([m.get("title") for m in by_source["conversation-hub"]], ["Lemur planning", None])
        self.assertTrue(all(match["in_draft"] for match in result["matches"]))
        text = json.dumps(result)
        for private in ("PRIVATE-BODY", "PRIVATE-DERIVED", "dry run", "snippet", "abs_path"):
            self.assertNotIn(private, text)
        self.assertTrue(all(result["coverage"][source]["searched"] for source in result["coverage"]))
        # The draft plus the four missing fields is a valid packet.
        self.service.handoff_submit({**draft, "handoff_id": "next-1", "mode": "request",
                                     "sender": "a", "recipient": "b"})

    def test_missing_caches_are_reported_not_built(self) -> None:
        result = self.service.handoff_prepare({"query": "lemur migration"})
        self.assertFalse(self.fabric.db_path.exists())
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["draft"], {"scope": [], "blockers": [], "source_refs": []})
        self.assertIn("context_snapshot", result["missing_fields"])
        self.assertFalse(result["coverage"]["fabric"]["searched"])
        self.assertFalse(result["coverage"]["conversation-hub"]["searched"])
        self.assertIn("index-hub", result["coverage"]["conversation-hub"]["reason"])
        self.assertEqual(result["coverage"]["handoff"], {"searched": True, "packets_scanned": 0})

    def test_conversation_hub_can_be_left_out_and_limit_and_cap_apply(self) -> None:
        self.add_conversations([(f"{n:02d}", f"Otter {n}", "user: otter survey", 0, f"2026-01-{n + 1:02d}T00:00:00Z")
                                for n in range(8)])
        for n in range(8):
            self.service.handoff_submit(packet(f"otter-{n}", ["river"], "Survey the otter habitat."))
        without = self.service.handoff_prepare({"query": "otter", "include_conversation_hub": False})
        self.assertEqual({m["source"] for m in without["matches"]}, {"handoff"})
        self.assertEqual(without["coverage"]["conversation-hub"], {"searched": False, "reason": "Not requested."})
        limited = self.service.handoff_prepare({"query": "otter", "limit": 2})
        self.assertEqual([m["source"] for m in limited["matches"]],
                         ["handoff", "conversation-hub", "handoff", "conversation-hub"])
        self.assertEqual([m["ref"] for m in limited["matches"] if m["source"] == "handoff"],
                         ["handoff:otter-7", "handoff:otter-6"])
        own = [{"ref": f"urn:synthetic:{n}", "revision": None} for n in range(17)]
        capped = self.service.handoff_prepare({"query": "otter", "limit": 4, "source_refs": own})
        self.assertEqual(len(capped["draft"]["source_refs"]), 20)
        self.assertEqual(capped["draft"]["source_refs"][:17], own)
        self.assertEqual(capped["references_omitted"], 5)
        self.assertEqual(sum(not m["in_draft"] for m in capped["matches"]), 5)
        repeat = self.service.handoff_prepare({"query": "otter", "source_refs": limited["draft"]["source_refs"]})
        self.assertEqual(len({(r["ref"], r["revision"]) for r in repeat["draft"]["source_refs"]}),
                         len(repeat["draft"]["source_refs"]))

    def test_scope_alone_ranks_exact_label_matches_before_text_matches(self) -> None:
        self.service.handoff_submit(packet("a", ["billing"], "Reconcile invoices."))
        self.service.handoff_submit(packet("b", ["billing-eu"], "Unrelated task."))
        info = packet("c", ["billing"], "x", mode="information")
        del info["requested_action"]
        self.service.handoff_submit(info)
        result = self.service.handoff_prepare({"scope": ["billing"]})
        # "billing-eu" is not the same label, but its text still matches the term "billing".
        self.assertEqual([(m["ref"], m["shared_scope"]) for m in result["matches"]],
                         [("handoff:c", ["billing"]), ("handoff:a", ["billing"]), ("handoff:b", [])])
        self.assertEqual(result["matches"][0]["mode"], "information")

    def test_earlier_handoffs_match_on_context_and_reported_results(self) -> None:
        self.service.handoff_submit(packet("ctx", ["x"], "Do the thing.", context_snapshot="Concerns the heron ledger."))
        self.service.handoff_submit(packet("res", ["y"], "Do another thing."))
        self.service.handoff_result({
            "result_id": "res-1", "handoff_id": "res", "responder": "synthetic-recipient", "outcome": "completed",
            "summary": "Heron ledger reconciled.", "blockers": [], "source_refs": []})
        self.service.handoff_submit(packet("none", ["z"], "Unrelated."))
        result = self.service.handoff_prepare({"query": "herons ledger", "scope": ["x"]})
        self.assertEqual([m["ref"] for m in result["matches"]], ["handoff:ctx", "handoff:res"])
        self.assertEqual([(m["shared_scope"], m["matched_text"], m["state"]) for m in result["matches"]],
                         [(["x"], True, "received"), ([], True, "completed")])
        self.assertNotIn("heron", json.dumps(result["matches"]).lower())

    def test_invalid_input_is_refused_without_echoing_it(self) -> None:
        secret = "ghp_" + "a" * 30
        bad = (
            None, {}, {"scope": []}, {"query": "  "}, {"query": "the of and"}, {"query": secret},
            {"query": "ok", "authority": "approved"}, {"query": "ok", "limit": 0}, {"query": "ok", "limit": 11},
            {"query": "ok", "limit": True}, {"query": "ok", "include_conversation_hub": "yes"},
            {"query": "ok", "scope": "billing"}, {"query": "ok", "scope": [1]},
            {"query": "ok", "source_refs": [{"ref": "x"}]}, {"query": "ok", "source_refs": [{"ref": secret, "revision": None}]},
            {"query": "ok", "source_refs": [{"ref": "x", "revision": None}] * 21},
            {"query": "ok", "context_snapshot": "x" * 20001}, {"query": "x" * 2001},
        )
        for payload in bad:
            with self.assertRaises(PhoneHomeError, msg=repr(payload)[:80]) as caught:
                self.service.handoff_prepare(payload)
            self.assertNotIn("ghp_", str(caught.exception))
        self.assertEqual(self.service.list()["total"], 0)


if __name__ == "__main__":
    unittest.main()
