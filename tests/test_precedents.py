"""Synthetic, caller-supplied precedent retrieval and evidence-history tests."""

import unittest
from unittest.mock import patch

from control_plane.precedents import PrecedentError, find_precedents, inspect_precedent


def event(event_id, outcome, need, scope, summary, *, event_type="observation", target_id="",
          source_ref=None, revision="test-run-1"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "target_id": target_id,
        "need": need,
        "outcome": outcome,
        "scope": scope,
        "summary": summary,
        "source_ref": source_ref or f"product-a/reports/{event_id}.json",
        "revision": revision,
    }


def record(record_id, impl_revision, observations, *, technique_id="PAT-9001",
           title="Bounded streaming CSV ingestion", summary="Process delimited input incrementally."):
    return {
        "record_id": record_id,
        "record_revision": f"sha256:{record_id}",
        "record_ref": f"product-a/knowledge/{record_id}.md",
        "technique": {"id": technique_id, "title": title, "summary": summary},
        "implementation": {
            "id": "csv-reader" if technique_id == "PAT-9001" else "json-reader",
            "source_ref": "product-a/src/csv.py" if technique_id == "PAT-9001" else "product-b/src/json.py",
            "revision": impl_revision,
        },
        "observations": observations,
    }


SCOPE_OK = {"runtime": "Python 3.12", "input": "valid UTF-8 CSV", "constraints": "network writes disabled"}
SCOPE_BAD = {"runtime": "Python 3.12", "input": "invalid UTF-8 CSV", "constraints": "network writes prohibited"}
SCOPE_UNKNOWN = {"runtime": "Python 3.13", "input": "invalid UTF-8 CSV", "constraints": "network writes disabled"}


def precedent_records():
    first = record("FND-9001", "commit-a", [
        event("csv-success-a", "success", "streaming CSV ingestion", SCOPE_OK,
              "Valid file completed within the memory bound."),
        event("csv-failure-a", "failure", "streaming CSV ingestion malformed UTF-8",
              SCOPE_BAD, "Malformed UTF-8 caused a partial network write."),
        event("csv-correction-a", "mixed", "streaming CSV ingestion malformed UTF-8",
              SCOPE_BAD, "Review confirmed malformed UTF-8 caused a partial network write; evidence remains mixed.",
              event_type="correction", target_id="csv-failure-a"),
    ])
    second = record("FND-9002", "commit-b", [
        event("csv-unknown-b", "unknown", "streaming CSV ingestion malformed UTF-8",
              SCOPE_UNKNOWN, "No execution evidence was collected for invalid bytes."),
    ])
    unrelated = record("FND-9003", "commit-json", [
        event("json-failure", "failure", "reject duplicate JSON manifest keys",
              {"runtime": "Python 3.12", "input": "JSON manifest", "constraints": "strict parsing"},
              "Duplicate keys were silently accepted."),
    ], technique_id="PAT-9002", title="Strict JSON manifest parsing",
       summary="Reject duplicate keys in configuration manifests.")
    return [first, second, unrelated]


def isolation_precedents():
    success = record("FND-9101", "release-a", [
        event("isolation-control", "success", "keep private records isolated per account",
              {"runtime": "hosted web service", "input": "two test accounts", "constraints": "private user data"},
              "Synthetic control: account-scoped reads returned only the requesting test account's records.",
              source_ref="example-product-a/reports/isolation-control.json"),
    ], technique_id="PAT-9101", title="Account-scoped data access",
       summary="Apply the requesting account boundary to private record reads.")
    success["implementation"] = {
        "id": "account-filtered-reader",
        "source_ref": "example-product-a/src/account_reader.py",
        "revision": "release-a",
    }
    failed_transfer = record("FND-9102", "release-b", [
        event("isolation-transfer-failure", "failure",
              "keep private records isolated per account",
              {"runtime": "hosted web service", "input": "private user data", "constraints": "shared cache"},
              "Synthetic transfer failure: an unscoped cache key returned another test account's record.",
              source_ref="example-product-b/reports/isolation-transfer.json",
              revision="test-run-b"),
    ], technique_id="PAT-9102", title="Shared-cache adaptation",
       summary="Adapt account-scoped reads to a shared cache.")
    failed_transfer["implementation"] = {
        "id": "shared-cache-reader",
        "source_ref": "example-product-b/src/cache_reader.py",
        "revision": "release-b",
    }
    return [success, failed_transfer]


class TestPrecedentLookup(unittest.TestCase):
    def test_fixed_query_set_relevance_is_separate_from_outcome(self):
        records = precedent_records()
        queries = [
            ("avoid partial network write invalid UTF-8 streaming CSV", ("PAT-9001", "commit-a")),
            ("reject duplicate JSON keys in manifests", ("PAT-9002", "commit-json")),
        ]
        hits = 0
        for query, expected in queries:
            with self.subTest(query=query):
                result = find_precedents(query, records)
                self.assertTrue(result["results"])
                top = result["results"][0]
                self.assertEqual((top["technique"]["id"], top["implementation"]["revision"]), expected)
                self.assertGreater(top["ranking"]["relevance_score"], 0)
                self.assertNotIn("success_rate", top)
                hits += 1
        self.assertEqual(hits, len(queries), "synthetic top-result need-query hit rate")
        self.assertEqual(find_precedents("browser canvas image zoom", records)["results"], [])
        csv_only = find_precedents(
            "streaming CSV valid UTF-8",
            records,
            {"input": "valid UTF-8 CSV"},
        )["results"]
        self.assertTrue(csv_only)
        self.assertTrue(all(item["technique"]["id"] == "PAT-9001" for item in csv_only))
        self.assertFalse(any("Duplicate keys were silently accepted" in warning
                             for item in csv_only for warning in item["warnings"]))

    def test_problem_wording_finds_cross_product_isolation_and_failed_transfer(self):
        records = isolation_precedents()
        query = "prevent private user data crossing accounts; enforce tenant isolation"
        result = find_precedents(
            query,
            records,
            {"runtime": "hosted web service", "input": "private user data", "constraints": "account isolation"},
        )
        self.assertEqual(len(result["results"]), 2)
        failed, control = result["results"]
        self.assertEqual(failed["implementation"]["id"], "shared-cache-reader")
        self.assertTrue(failed["ranking"]["avoidance_priority"])
        self.assertEqual(failed["source_records"][0]["record_id"], "FND-9102")
        self.assertTrue(any("unscoped cache key" in warning for warning in failed["warnings"]))
        self.assertEqual(control["implementation"]["id"], "account-filtered-reader")
        self.assertEqual(control["outcome_summary"]["observed_outcomes"], ["success"])
        self.assertTrue(any("not independently verified" in warning for warning in [
            result["notice"],
        ]))
        self.assertTrue(any("not assessed" in warning for warning in [
            control["applicability"],
        ]))

    def test_avoidance_retrieves_scoped_negative_history_without_cross_revision_blame(self):
        result = find_precedents(
            "avoid partial network write invalid UTF-8 streaming CSV",
            precedent_records(),
            {"runtime": "Python 3.12", "input": "invalid UTF-8 CSV", "constraints": "network writes prohibited"},
        )
        by_revision = {item["implementation"]["revision"]: item for item in result["results"]}
        self.assertIn("commit-a", by_revision)
        self.assertIn("commit-b", by_revision)
        failed = by_revision["commit-a"]
        self.assertTrue(failed["ranking"]["avoidance_priority"])
        self.assertIn("mixed", failed["outcome_summary"]["observed_outcomes"])
        self.assertTrue(any("partial network write" in warning for warning in failed["warnings"]))
        self.assertEqual(failed["scope_comparison"]["FND-9001:csv-failure-a"]["input"], "match")
        unaffected = by_revision["commit-b"]
        self.assertEqual(unaffected["outcome_summary"]["observed_outcomes"], ["unknown"])
        self.assertTrue(any("unknown" in warning for warning in unaffected["warnings"]))
        self.assertFalse(any("partial network write" in warning for warning in unaffected["warnings"]))

    def test_inspection_preserves_correction_and_revision_history(self):
        inspected = inspect_precedent("csv-reader", precedent_records())
        self.assertEqual({v["implementation"]["revision"] for v in inspected["variants"]},
                         {"commit-a", "commit-b"})
        first = next(v for v in inspected["variants"] if v["implementation"]["revision"] == "commit-a")
        evidence = {item["event_id"]: item for item in first["evidence_history"]}
        self.assertEqual(evidence["csv-failure-a"]["effective_outcome"], "mixed")
        self.assertEqual(evidence["csv-failure-a"]["corrections"][0]["event_id"], "csv-correction-a")
        self.assertEqual(evidence["csv-failure-a"]["outcome"], "failure")
        self.assertEqual(evidence["csv-success-a"]["effective_outcome"], "success")
        self.assertEqual([event["event_id"] for event in first["event_history"]],
                         ["csv-success-a", "csv-failure-a", "csv-correction-a"])

    def test_duplicate_evidence_is_visible_but_not_counted_twice(self):
        duplicate = dict(precedent_records()[0])
        duplicate["record_id"] = "FND-9010"
        duplicate["record_ref"] = "product-a/knowledge/FND-9010.md"
        duplicate["record_revision"] = "sha256:FND-9010"
        duplicate["observations"] = [dict(precedent_records()[0]["observations"][0])]
        result = find_precedents("streaming CSV valid UTF-8", [precedent_records()[0], duplicate])
        top = result["results"][0]
        self.assertEqual(top["outcome_summary"]["observed_outcomes"], ["mixed", "success"])
        self.assertEqual(top["outcome_summary"]["evidence_entries"], 2)
        self.assertEqual(top["evidence_quality"]["duplicate_observations"], 1)
        self.assertTrue(any("not independent support" in warning for warning in top["warnings"]))
        duplicate_history = [e for e in top["relevant_evidence"] if e["duplicate_of"]]
        self.assertEqual(len(duplicate_history), 1)

    def test_dispute_unknown_outcome_and_source_unknown_remain_explicit(self):
        disputed = record("FND-9020", "commit-a", [
            event("unknown-observation", "unknown", "streaming CSV parsing", SCOPE_UNKNOWN,
                  "No run was observed.", source_ref="product-a/reports/unavailable.json", revision=None),
            event("dispute-event", "unknown", "", {"runtime": "", "input": "", "constraints": ""},
                  "The cited report does not include execution logs.", event_type="dispute",
                  target_id="unknown-observation", source_ref="product-a/reviews/dispute.md", revision=None),
        ])
        found = find_precedents("streaming CSV parsing", [disputed])["results"][0]
        self.assertEqual(found["outcome_summary"]["observed_outcomes"], ["unknown"])
        self.assertIsNone(found["relevant_evidence"][0]["revision"])
        self.assertTrue(any("disputed" in warning for warning in found["warnings"]))
        self.assertTrue(any("unknown" in warning for warning in found["warnings"]))
        history = inspect_precedent("csv-reader", [disputed])["variants"][0]["evidence_history"]
        self.assertEqual(history[0]["disputes"][0]["event_id"], "dispute-event")
        event_history = inspect_precedent("csv-reader", [disputed])["variants"][0]["event_history"]
        self.assertEqual([event["event_type"] for event in event_history], ["observation", "dispute"])

    def test_invalid_or_secret_bearing_data_fails_closed_without_source_access(self):
        with patch("pathlib.Path.read_text", side_effect=AssertionError("source read")):
            with self.assertRaises(PrecedentError):
                find_precedents("streaming csv", [dict(precedent_records()[0], unexpected="field")])
            malformed_ref = precedent_records()
            malformed_ref[0]["implementation"]["source_ref"] = {"path": "not a locator string"}
            with self.assertRaises(PrecedentError):
                find_precedents("streaming csv", malformed_ref)
            unsafe = precedent_records()
            unsafe[0]["implementation"]["source_ref"] = "ghp_" + "a" * 30
            with self.assertRaises(PrecedentError):
                find_precedents("streaming csv", unsafe)
            with self.assertRaises(PrecedentError):
                find_precedents("streaming csv", precedent_records(), limit=True)
            oversized = record("FND-9040", "commit-large", [
                event(f"large-{index}", "unknown", "large evidence payload", SCOPE_UNKNOWN, "x" * 4000)
                for index in range(17)
            ])
            with self.assertRaisesRegex(PrecedentError, "64 KiB"):
                find_precedents("large evidence payload", [oversized])

    def test_correction_must_target_an_earlier_observation(self):
        invalid = record("FND-9030", "commit-a", [
            event("bad-correction", "failure", "streaming CSV", SCOPE_BAD, "Correction without base.",
                  event_type="correction", target_id="missing"),
        ])
        with self.assertRaisesRegex(PrecedentError, "earlier observation"):
            find_precedents("streaming CSV", [invalid])


if __name__ == "__main__":
    unittest.main()
