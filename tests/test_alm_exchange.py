"""Synthetic coverage for read-only ALM lifecycle ledger inspection (DNCP-012)."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from importlib.metadata import PackageNotFoundError
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_plane import alm_exchange
from control_plane.alm_exchange import AlmExchangeError, inspect_ledger
from control_plane.cli import main
from control_plane.material_pins import ALM_COMMIT, ALM_VERSION

try:
    CORE = alm_exchange.require_alm_core()
except AlmExchangeError:
    CORE = None

PRIVATE = "PRIVATE-SKILL-BODY"


class AlmCoreAbsentTests(unittest.TestCase):
    def test_missing_or_unverified_core_is_an_actionable_refusal(self) -> None:
        self.addCleanup(alm_exchange.clear_alm_core_cache)
        for failure, code in ((PackageNotFoundError("alm-lifecycle-core"), "capability_missing"),
                              (ValueError("alm-lifecycle-core has unverified version/source"), "capability_unverified")):
            alm_exchange.clear_alm_core_cache()
            with patch("control_plane.alm_exchange._prepare_owned", side_effect=failure):
                with self.assertRaises(AlmExchangeError) as caught:
                    inspect_ledger(Path("absent.json"))
            self.assertEqual((caught.exception.code, caught.exception.status), (code, 503))
            self.assertIn("devnet-control-plane[alm]", str(caught.exception))
            self.assertIn(ALM_COMMIT, str(caught.exception))


@unittest.skipUnless(CORE, "Requires the optional pinned alm-lifecycle-core distribution")
class AlmLedgerInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        skill = self.component("skill.triage", "skill", "skills/triage.md", f"# Triage\n{PRIVATE}\n")
        prompt = self.component("prompt.review", "prompt", "prompts/review.md", "Review carefully.\n")
        agent = self.component("agent.reviewer", "agent", "agents/reviewer.md", "You review.\n",
                               dependencies=[CORE.ref(skill), CORE.ref(prompt)])
        self.records = [agent, skill, prompt]
        self.manifest = self.write(self.records)

    def component(self, identity: str, kind: str, path: str, content: str, dependencies=(), version="1.0.0") -> dict:
        target = self.workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
        return CORE.seal({
            "id": identity, "kind": kind, "version": version, "upstream_refs": ["PRJ-0005"],
            "files": [{"path": path, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "content": content}],
            "dependencies": list(dependencies),
            "origin": {"repository": "synthetic/repo", "revision": "0" * 40, "locator": path},
        })

    def write(self, records: list[dict], name: str = "ledger.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(CORE.envelope(records)), encoding="utf-8")
        return path

    def assert_error(self, code: str, *args, **kwargs) -> AlmExchangeError:
        with self.assertRaises(AlmExchangeError) as caught:
            inspect_ledger(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(PRIVATE, str(caught.exception))
        return caught.exception

    def test_valid_ledger_lists_components_without_content_or_trust(self) -> None:
        before = self.manifest.read_bytes()
        with patch("urllib.request.urlopen", side_effect=AssertionError("no fetch")), \
             patch("subprocess.run", side_effect=AssertionError("no execution")):
            result = inspect_ledger(self.manifest)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["ledger.json", "workspace"])
        self.assertEqual((result["valid"], result["trusted"], result["live_deployment_verified"]), (True, False, False))
        self.assertFalse(result["files_compared_with_root"])
        self.assertEqual(result["validator"], {"package": "alm-lifecycle-core", "version": ALM_VERSION, "commit": ALM_COMMIT})
        self.assertEqual(result["contract"], {"registry": "alm-lifecycle", "schema_version": 1, "owner": "PRJ-0005"})
        self.assertEqual(result["ledger"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(result["ledger"]["kinds"], {"agent": 1, "prompt": 1, "skill": 1})
        self.assertEqual([c["id"] for c in result["components"]], ["agent.reviewer", "prompt.review", "skill.triage"])
        agent = result["components"][0]
        self.assertEqual(agent["dependencies"], [CORE.ref(self.records[1]), CORE.ref(self.records[2])])
        self.assertEqual(agent["revision"], self.records[0]["revision"])
        self.assertEqual(agent["origin"]["repository"], "synthetic/repo")
        self.assertEqual(sorted(agent["files"][0]), ["path", "sha256"])
        self.assertEqual(result["releases"], [])
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertIn("no component is trusted", result["notice"])

    def test_filters_select_by_kind_and_id(self) -> None:
        self.assertEqual([c["id"] for c in inspect_ledger(self.manifest, kind="skill")["components"]], ["skill.triage"])
        self.assertEqual([c["kind"] for c in inspect_ledger(self.manifest, component_id="prompt.review")["components"]],
                         ["prompt"])
        self.assertEqual(self.assert_error("not_found", self.manifest, kind="tool").status, 404)
        self.assert_error("not_found", self.manifest, component_id="absent")
        self.assert_error("not_found", self.manifest, kind="skill", component_id="prompt.review")

    def test_root_comparison_reports_drift_as_invalid(self) -> None:
        self.assertTrue(inspect_ledger(self.manifest, self.workspace)["files_compared_with_root"])
        (self.workspace / "skills" / "triage.md").write_text("changed", encoding="utf-8")
        error = self.assert_error("ledger_invalid", self.manifest, self.workspace)
        self.assertIn("workspace drift: skills/triage.md", str(error))
        self.assertTrue(inspect_ledger(self.manifest)["valid"])
        (self.workspace / "skills" / "triage.md").unlink()
        self.assert_error("ledger_invalid", self.manifest, self.workspace)
        self.assert_error("unavailable", self.manifest, self.root / "absent-root")

    def test_tampered_malformed_and_unavailable_ledgers_are_refused(self) -> None:
        tampered = dict(self.records[1], version="9.9.9")
        self.assertIn("revision hash mismatch", str(self.assert_error("ledger_invalid", self.write([tampered], "t.json"))))
        edited = json.loads(json.dumps(self.records[1]))
        edited["files"][0]["content"] += PRIVATE
        self.assert_error("ledger_invalid", self.write([edited], "e.json"))
        dangling = self.component("agent.orphan", "agent", "agents/o.md", "x",
                                  dependencies=[{"id": "skill.absent", "revision": "f" * 64}])
        self.assert_error("ledger_invalid", self.write([dangling], "d.json"))
        for name, raw in (("empty.json", b""), ("text.json", b"not json"), ("bytes.json", b"\xff\xfe"),
                          ("list.json", b"[]"), ("dup.json", b'{"registry": 1, "registry": 2}'),
                          ("other.json", json.dumps({"registry": "other", "schema_version": 1,
                                                     "owner": "PRJ-0005", "entries": [self.records[1]]}).encode())):
            path = self.root / name
            path.write_bytes(raw)
            self.assert_error("ledger_invalid", path)
        self.assertEqual(self.assert_error("unavailable", self.root / "absent.json").status, 503)
        self.assert_error("unavailable", self.workspace)
        with patch.object(alm_exchange, "MAX_MANIFEST_BYTES", 10):
            self.assert_error("unavailable", self.manifest)

    def test_cli_prints_the_inspection_and_coded_errors(self) -> None:
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["--data-dir", str(self.root / "data"), "alm", "inspect", "--manifest", str(self.manifest),
                         "--root", str(self.workspace), "--kind", "agent"])
        self.assertEqual((code, error.getvalue()), (0, ""))
        printed = json.loads(output.getvalue())
        self.assertEqual([c["id"] for c in printed["components"]], ["agent.reviewer"])
        self.assertFalse(printed["trusted"])
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["alm", "inspect", "--manifest", str(self.root / "absent.json")])
        self.assertEqual((code, output.getvalue()), (1, ""))
        self.assertEqual(json.loads(error.getvalue())["code"], "unavailable")
        self.assertNotIn(str(self.root), error.getvalue())


if __name__ == "__main__":
    unittest.main()
