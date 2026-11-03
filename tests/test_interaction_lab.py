"""Offline regressions for persisted Interaction Lab execution provenance."""

from __future__ import annotations

from contextlib import closing
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from control_plane.interaction_lab import InteractionFrameEngine
from control_plane.ui import ControlPlaneWorkbench


class TestInteractionLabProvenance(unittest.TestCase):
    frames = ["baseline_direct", "cute_mentor_builder"]

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workbench = ControlPlaneWorkbench(
            factory_root=self.root / "factory",
            network_root=self.root / "network",
            data_dir=self.root / "data",
        )
        self.engine = self.workbench.interaction_lab
        env = patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-test-key",
            "OPENAI_BASE_URL": "https://provider.invalid/v1",
            "INTERACTION_LAB_MODEL": "mock-model",
        })
        env.start()
        self.addCleanup(env.stop)
        provider = patch("control_plane.interaction_lab.urllib.request.urlopen")
        self.provider = provider.start()
        self.provider.side_effect = AssertionError("Unexpected provider invocation")
        self.addCleanup(provider.stop)

    @staticmethod
    def response(payload: object) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    def success(self) -> MagicMock:
        return self.response({"choices": [{"message": {"content": "Synthetic live output"}}]})

    def run_evaluation(self) -> dict:
        return self.engine.run_side_by_side_evaluation("Synthetic task", self.frames)

    def assert_persisted(self, run: dict) -> None:
        with closing(self.engine._connect()) as conn:
            row = conn.execute(
                "SELECT execution_mode, variants_json FROM evaluation_runs WHERE run_id = ?",
                (run["run_id"],),
            ).fetchone()
        self.assertEqual(row["execution_mode"], run["execution_mode"])
        self.assertEqual(json.loads(row["variants_json"]), run["variants"])
        reloaded = InteractionFrameEngine(db_path=self.engine.db_path)
        self.assertEqual(reloaded.get_run(run["run_id"]), run)
        self.assertEqual(reloaded.list_runs(), [run])

    def test_failed_first_live_second(self) -> None:
        self.assert_mixed_failure(failure_first=True)

    def test_live_first_failed_second(self) -> None:
        self.assert_mixed_failure(failure_first=False)

    def assert_mixed_failure(self, failure_first: bool) -> None:
        failure = urllib.error.URLError("sensitive provider detail must not be stored")
        self.provider.side_effect = (
            [failure, self.success()] if failure_first else [self.success(), failure]
        )
        run = self.run_evaluation()
        self.assertEqual(self.provider.call_count, 2)
        self.assertEqual(run["execution_mode"], "mixed (live call failed)")
        failed, live = run["variants"] if failure_first else reversed(run["variants"])
        self.assertEqual(failed["execution_mode"], "deterministic-preview")
        self.assertEqual(failed["live_call_status"], "failed")
        self.assertEqual(failed["requested_model"], "mock-model")
        self.assertEqual(failed["live_call_error"]["type"], "URLError")
        self.assertIn("Deterministic Frame Preview", failed["output_text"])
        self.assertEqual(live["execution_mode"], "live-llm:mock-model")
        self.assertEqual(live["live_call_status"], "succeeded")
        self.assertIsNone(live["live_call_error"])
        self.assertEqual(live["output_text"], "Synthetic live output")
        self.assertNotIn("sensitive provider detail", json.dumps(run))
        self.assert_persisted(run)

        html = self.workbench.render_interaction_tab(run["run_id"])
        self.assertIn("mixed (live call failed)", html)
        self.assertEqual(html.count("Framed Output (deterministic-preview)"), 1)
        self.assertEqual(html.count("Framed Output (live-llm:mock-model)"), 1)
        self.assertIn("not a live model result", html)
        self.assertIn("Execution Mode</th>", html)
        scored = self.engine.record_human_rating(
            run["run_id"], failed["frame_id"], 4, 4, 4, 4, winner=True,
        )
        self.assertEqual(scored["execution_mode"], run["execution_mode"])
        for before, after in zip(run["variants"], scored["variants"]):
            for key in ("execution_mode", "live_call_status", "requested_model", "live_call_error"):
                self.assertEqual(before[key], after[key])
        self.assert_persisted(scored)

    def test_all_live(self) -> None:
        self.provider.side_effect = [self.success(), self.success()]
        run = self.run_evaluation()
        self.assertEqual(run["execution_mode"], "live-llm:mock-model")
        self.assertTrue(all(v["live_call_status"] == "succeeded" for v in run["variants"]))
        self.assert_persisted(run)

    def test_mixed_live_models_without_failure(self) -> None:
        self.provider.side_effect = [self.success(), self.success()]
        original = self.engine._try_live_llm

        def complete(system_prompt: str, user_prompt: str) -> tuple:
            model = "mock-first" if self.provider.call_count == 0 else "mock-second"
            with patch.dict(os.environ, {"INTERACTION_LAB_MODEL": model}):
                return original(system_prompt, user_prompt)

        with patch.object(self.engine, "_try_live_llm", side_effect=complete):
            run = self.run_evaluation()
        self.assertEqual(run["execution_mode"], "mixed")
        self.assertEqual(
            [v["execution_mode"] for v in run["variants"]],
            ["live-llm:mock-first", "live-llm:mock-second"],
        )
        self.assert_persisted(run)

    def test_no_credentials_preview_without_live_attempt(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            run = self.run_evaluation()
        self.provider.assert_not_called()
        self.assertEqual(run["execution_mode"], "deterministic-preview")
        for variant in run["variants"]:
            self.assertEqual(variant["execution_mode"], "deterministic-preview")
            self.assertEqual(variant["live_call_status"], "not-requested")
            self.assertIsNone(variant["requested_model"])
            self.assertIsNone(variant["live_call_error"])
        self.assert_persisted(run)
        self.assertIn("No live call requested", self.workbench.render_interaction_tab())

    def test_all_failed_preview_exposes_http_status(self) -> None:
        self.provider.side_effect = urllib.error.HTTPError(
            "https://provider.invalid", 503, "sensitive reason", {}, None,
        )
        run = self.run_evaluation()
        self.assertEqual(run["execution_mode"], "deterministic-preview (live call failed)")
        for variant in run["variants"]:
            self.assertEqual(variant["live_call_status"], "failed")
            self.assertEqual(variant["live_call_error"]["http_status"], 503)
        self.assert_persisted(run)
        html = self.workbench.render_interaction_tab()
        self.assertIn("HTTP 503", html)
        self.assertNotIn("sensitive reason", html)
        self.assertNotIn("Framed Output (live-llm", html)

    def test_unusable_completions_are_failed_previews(self) -> None:
        for content in (None, "", "   ", 17, [], {}):
            with self.subTest(content=content):
                self.provider.side_effect = None
                self.provider.return_value = self.response({"choices": [{"message": {"content": content}}]})
                output, provenance = self.engine._try_live_llm("Synthetic system", "Synthetic task")
                self.assertIsNone(output)
                self.assertEqual(provenance["execution_mode"], "deterministic-preview")
                self.assertEqual(provenance["live_call_status"], "failed")
                self.assertEqual(provenance["live_call_error"]["type"], "ValueError")

    def test_malformed_response_is_failed_preview(self) -> None:
        for payload in ({}, {"choices": []}, {"choices": [{"message": {}}]}, None):
            with self.subTest(payload=payload):
                self.provider.side_effect = None
                self.provider.return_value = self.response(payload)
                output, provenance = self.engine._try_live_llm("Synthetic system", "Synthetic task")
                self.assertIsNone(output)
                self.assertEqual(provenance["live_call_status"], "failed")
                self.assertEqual(provenance["execution_mode"], "deterministic-preview")

    def test_transport_and_json_failures_are_failed_previews(self) -> None:
        for failure in (TimeoutError("sensitive timeout"), http.client.IncompleteRead(b"sensitive body")):
            with self.subTest(failure=type(failure).__name__):
                self.provider.side_effect = failure
                output, provenance = self.engine._try_live_llm("Synthetic system", "Synthetic task")
                self.assertIsNone(output)
                self.assertEqual(provenance["live_call_status"], "failed")
                self.assertEqual(provenance["live_call_error"]["type"], type(failure).__name__)
                self.assertNotIn("sensitive", json.dumps(provenance))
        response = self.response({})
        response.__enter__.return_value.read.return_value = b"invalid json"
        self.provider.side_effect = None
        self.provider.return_value = response
        output, provenance = self.engine._try_live_llm("Synthetic system", "Synthetic task")
        self.assertIsNone(output)
        self.assertEqual(provenance["live_call_status"], "failed")
        self.assertEqual(provenance["live_call_error"]["type"], "JSONDecodeError")

    def test_run_label_is_derived_and_partial_provenance_is_unknown(self) -> None:
        self.provider.side_effect = [self.success(), self.success()]
        run = self.run_evaluation()
        with closing(self.engine._connect()) as conn:
            conn.execute(
                "UPDATE evaluation_runs SET execution_mode = 'incorrect-label' WHERE run_id = ?",
                (run["run_id"],),
            )
            conn.commit()
        self.assertEqual(self.engine.get_run(run["run_id"]), run)
        self.assertEqual(self.engine.list_runs(), [run])

        del run["variants"][0]["live_call_status"]
        with closing(self.engine._connect()) as conn:
            conn.execute(
                "UPDATE evaluation_runs SET variants_json = ? WHERE run_id = ?",
                (json.dumps(run["variants"]), run["run_id"]),
            )
            conn.commit()
        loaded = self.engine.get_run(run["run_id"])
        self.assertEqual(loaded["execution_mode"], "unknown")
        self.assertEqual(loaded["variants"][0]["execution_mode"], "unknown")
        self.assertEqual(loaded["variants"][1]["execution_mode"], "live-llm:mock-model")
        self.assertEqual(self.engine.list_runs(), [loaded])

    def test_legacy_records_remain_unknown_and_unmodified_on_reads(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            run = self.run_evaluation()
        legacy_variants = [
            {key: value for key, value in v.items() if key not in {
                "execution_mode", "live_call_status", "requested_model", "live_call_error",
            }} for v in run["variants"]
        ]
        for old_label in (
            "live-llm:mock-model", "deterministic-preview",
            "deterministic-preview (live call failed: old error)",
        ):
            with self.subTest(old_label=old_label):
                raw = json.dumps(legacy_variants)
                with closing(self.engine._connect()) as conn:
                    conn.execute(
                        "UPDATE evaluation_runs SET execution_mode = ?, variants_json = ? WHERE run_id = ?",
                        (old_label, raw, run["run_id"]),
                    )
                    conn.commit()
                reloaded = InteractionFrameEngine(db_path=self.engine.db_path)
                loaded = reloaded.get_run(run["run_id"])
                self.assertEqual(loaded["execution_mode"], "unknown")
                self.assertEqual(reloaded.list_runs(), [loaded])
                for variant in loaded["variants"]:
                    self.assertEqual(variant["execution_mode"], "unknown")
                    self.assertEqual(variant["live_call_status"], "unknown")
                    self.assertIsNone(variant["requested_model"])
                    self.assertIsNone(variant["live_call_error"])
                html = self.workbench.render_interaction_tab(run["run_id"])
                self.assertEqual(html.count("Framed Output (unknown)"), 2)
                self.assertIn("live success cannot be established", html)
                self.assertNotIn(old_label, html)
                with closing(self.engine._connect()) as conn:
                    row = conn.execute("SELECT * FROM evaluation_runs").fetchone()
                self.assertEqual(row["execution_mode"], old_label)
                self.assertEqual(row["variants_json"], raw)
                scored = reloaded.record_human_rating(run["run_id"], self.frames[0], 5, 5, 5, 5)
                self.assertEqual(scored["execution_mode"], "unknown")
                self.assertTrue(all(v["execution_mode"] == "unknown" for v in scored["variants"]))


if __name__ == "__main__":
    unittest.main()
