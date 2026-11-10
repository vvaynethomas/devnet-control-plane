"""Synthetic coverage for ranked, read-only search over stored handoffs."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_plane import handoff_search
from control_plane.phone_home import PhoneHome, PhoneHomeError


def packet(handoff_id: str, scope: list[str], action: str, **extra) -> dict:
    return {
        "handoff_id": handoff_id, "mode": "request", "sender": "synthetic-sender",
        "recipient": "synthetic-recipient", "scope": scope, "context_snapshot": "Synthetic context.",
        "requested_action": action, "blockers": [], "source_refs": [], **extra,
    }


def result(result_id: str, handoff_id: str, outcome: str, summary: str, blockers: list[str] | None = None) -> dict:
    return {"result_id": result_id, "handoff_id": handoff_id, "responder": "synthetic-recipient",
            "outcome": outcome, "summary": summary, "blockers": blockers or [], "source_refs": []}


class HandoffSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.service = PhoneHome(root / "factory", root / "network", root / "runtime")
        submit = self.service.handoff_submit
        submit(packet("title", ["zoo"], "Migrate the pelican registry."))
        submit(packet("context", ["zoo", "ops"], "Review a report.",
                      context_snapshot="Mentions the pelican registry once in passing among other words."))
        submit(packet("done", ["ops"], "Close the audit."))
        self.service.handoff_result(result("done-1", "done", "blocked", "Waiting.", ["Pelican export missing."]))
        self.service.handoff_result(result("done-2", "done", "completed", "Audit closed after the export arrived."))
        submit(packet("stuck", ["ops"], "Ship the heron build.", recipient="other-recipient"))
        self.service.handoff_result({**result("stuck-1", "stuck", "blocked", "Cannot ship.", ["No signing key."]),
                                     "responder": "other-recipient"})
        info = packet("note", ["zoo"], "x", mode="information", context_snapshot="Pelicans were counted.")
        del info["requested_action"]
        submit(info)

    def ids(self, **arguments) -> list[str]:
        return [item["handoff_id"] for item in self.service.handoff_search(**arguments)["handoffs"]]

    def test_query_ranks_across_action_context_and_results_in_any_state(self) -> None:
        before = self.service.list()["total"]
        with patch("urllib.request.urlopen", side_effect=AssertionError("no fetch")), \
             patch("subprocess.run", side_effect=AssertionError("no execution")):
            found = self.service.handoff_search(query="pelican registry")
        self.assertEqual(self.service.list()["total"], before)
        self.assertEqual(found["handoffs"][0]["handoff_id"], "title")
        self.assertEqual({item["handoff_id"] for item in found["handoffs"]}, {"title", "context", "done", "note"})
        self.assertEqual((found["total"], found["scanned"], found["truncated"]), (4, 5, False))
        done = next(item for item in found["handoffs"] if item["handoff_id"] == "done")
        self.assertEqual((done["state"], done["result_count"], done["blockers"]), ("completed", 2, []))
        self.assertIsNotNone(done["latest_result_at"])
        self.assertIn("[Pelican]", done["snippet"])
        self.assertEqual(done["ref"], "handoff:done")
        self.assertRegex(done["revision"], r"^sha256:[0-9a-f]{64}$")
        self.assertFalse(any(key.startswith("_") for item in found["handoffs"] for key in item))
        self.assertIn("untrusted", found["notice"])

    def test_filters_browse_and_blockers(self) -> None:
        self.assertEqual(self.ids(), ["note", "stuck", "done", "context", "title"])
        self.assertEqual(self.ids(limit=2), ["note", "stuck"])
        self.assertEqual(self.ids(scope="zoo"), ["note", "context", "title"])
        self.assertEqual(self.ids(scope="zo"), [])
        self.assertEqual(self.ids(recipient="other-recipient"), ["stuck"])
        self.assertEqual(self.ids(state="completed"), ["done"])
        self.assertEqual(self.ids(state="received"), ["note", "context", "title"])
        self.assertEqual(sorted(self.ids(query="pelican", scope="ops")), ["context", "done"])
        self.assertEqual(self.ids(query="pelican", state="blocked"), [])
        stuck = self.service.handoff_search(state="blocked")["handoffs"][0]
        self.assertEqual(stuck["blockers"], ["No signing key."])
        self.assertNotIn("snippet", stuck)
        self.assertEqual(self.ids(query="!!!"), [])
        self.assertEqual(self.ids(query="absentterm"), [])
        self.assertEqual(self.ids(query='pelican" OR x NEAR('), self.ids(query="pelican or x near"))

    def test_only_the_newest_packets_are_scanned(self) -> None:
        with patch.object(handoff_search, "MAX_SCANNED", 3):
            found = self.service.handoff_search()
        self.assertEqual((found["scanned"], found["truncated"]), (3, True))
        self.assertEqual([item["handoff_id"] for item in found["handoffs"]], ["note", "stuck", "done"])

    def test_invalid_arguments_are_refused(self) -> None:
        for arguments in ({"state": "approved"}, {"limit": 0}, {"limit": 51}, {"limit": True},
                          {"query": None}, {"query": "x" * 2001}, {"scope": 3}, {"recipient": "r" * 201},
                          {"query": "ghp_" + "a" * 30}):
            with self.assertRaises(PhoneHomeError, msg=repr(arguments)[:60]) as caught:
                self.service.handoff_search(**arguments)
            self.assertNotIn("ghp_", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
