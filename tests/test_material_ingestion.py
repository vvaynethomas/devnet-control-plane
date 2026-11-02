"""Explicit-input adapters, one-step intake and bounded ZIP handling."""

import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import warnings
import zipfile

from control_plane.cli import main
from control_plane.digester import MaterialReference
from control_plane.material_ingestion import (
    MAX_INPUT_BYTES, MAX_ITEMS, MAX_MEMBERS, MAX_OBSERVATIONS,
    MaterialError, SuppliedMaterialDigester,
)
from control_plane.phone_home import PhoneHome, PhoneHomeError
from control_plane.ui import ControlPlaneWorkbench, serve_control_plane


class TestMaterialIngestion(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = PhoneHome(self.root / "missing", self.root / "missing-network", self.root / "runtime")

    def payload(self, text: str = "Goal: preserve evidence", format: str = "text", name: str = "input.txt") -> dict:
        return {"kind": "material", "material": {"name": name, "format": format, "text": text}}

    def submit(self, text: str, format: str = "text", name: str = "input.txt", **extra) -> dict:
        return self.service.submit({**self.payload(text, format, name), **extra})

    def archive(self, members: list[tuple[str | zipfile.ZipInfo, bytes]], compression: int = zipfile.ZIP_STORED) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=compression) as archive:
            for name, raw in members:
                archive.writestr(name, raw)
        return output.getvalue()

    def zip_payload(self, raw: bytes) -> dict:
        return {"kind": "material", "material": {"name": "bundle.zip", "format": "zip",
                                                "base64": base64.b64encode(raw).decode()}}

    def test_one_step_no_repo_owner_agent_or_inventory_gate(self) -> None:
        with patch("control_plane.repo_metabolizer.RepositoryMetabolizer", side_effect=AssertionError("opt-in")), \
             patch.object(self.service, "check", side_effect=AssertionError("inventory gate")), \
             patch("subprocess.Popen", side_effect=AssertionError("execution")):
            receipt = self.submit("Intent: a general funnel\nunrelated observation", target="funnel")
        self.assertTrue(receipt["review"]["ingested"])
        self.assertFalse(receipt["review"]["acceptance_required"])
        self.assertFalse(receipt["review"]["automatic_promotion"])
        self.assertNotIn("source_repo", receipt)
        self.assertEqual(self.service.get(receipt["id"]), receipt)
        self.assertFalse((self.root / "runtime" / "digester.sqlite").exists())
        self.assertFalse((self.root / "missing").exists())
        self.assertFalse((self.root / "runtime" / "control_plane_fabric.sqlite").exists())

    def test_provenance_identity_revision_determinism_and_frequency(self) -> None:
        text = "Goal: reuse\nsame observation\nsame observation\nuntargeted body"
        payload = self.payload(text)
        payload["material"]["identity"] = "original:import-7"
        payload["source_ref"] = "source://example#section"
        payload["source_session"] = "fixture"
        payload["target"] = "reuse"
        payload["idempotency_key"] = "one"
        first = self.service.submit(payload)
        self.assertEqual(first, self.service.submit(payload))
        digest = first["digestion"]
        self.assertEqual(digest["material"]["revision"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(digest["material"]["identity"], "original:import-7")
        self.assertEqual(first["source_ref"], payload["source_ref"])
        self.assertEqual(first["source_session"], "fixture")
        repeated = next(g for g in digest["residue"]["items"] if g["count"] == 2)
        self.assertEqual([r["line"] for r in repeated["evidence"]], [2, 3])
        self.assertFalse(repeated["target_match"])
        self.assertEqual(len([i for i in digest["items"] if i["title"] == "same observation"]), 2)
        self.assertEqual(len({i["id"] for i in digest["items"]}), 4)
        self.assertFalse(digest["coverage"]["full_semantic_coverage"])
        with self.assertRaises(PhoneHomeError):
            self.service.submit({**payload, "material": {**payload["material"], "text": "changed"}})
        self.assertEqual(self.service.list()["total"], 1)
        long_text = "x" * 400 + " first\n" + "x" * 400 + " second"
        groups = self.submit(long_text)["digestion"]["residue"]["items"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["observation"], groups[1]["observation"])
        self.assertNotEqual(groups[0]["observation_sha256"], groups[1]["observation_sha256"])
        self.assertTrue(all(g["text_truncated"] for g in groups))

    def test_markdown_retains_body_and_fence_without_false_intent(self) -> None:
        digest = self.submit("# Topic\nGoal: safe reuse\nbody\n```python\nTODO: not a directive\n```\n", "markdown")["digestion"]
        self.assertEqual([i["category"] for i in digest["items"]], ["document_heading", "declared_direction"])
        groups = digest["residue"]["items"]
        self.assertTrue(any(g["observation"] == "body" for g in groups))
        self.assertTrue(any(g["observation"] == "TODO: not a directive" and not g["extracted_item"] for g in groups))

    def test_csv_rows_newlines_direction_and_ragged_coverage(self) -> None:
        digest = self.submit('name,direction\nfirst,"reuse\nsafely"\nsecond,extend,extra\n', "csv")["digestion"]
        rows = [i for i in digest["items"] if i["category"] == "csv_row"]
        self.assertEqual([i["provenance"]["line"] for i in rows], [2, 4])
        self.assertEqual(len([i for i in digest["items"] if i["category"] == "declared_direction"]), 2)
        self.assertEqual(digest["coverage"]["exclusions"]["csv_ragged_row"], 1)

    def test_html_static_text_only_no_script_or_fetch(self) -> None:
        text = '<h1>Topic</h1><p>Goal: reuse &amp; learn</p><script>raise("unsafe")</script><style>hidden</style><!-- residue --><a href="https://invalid.test">link</a>'
        with patch("urllib.request.urlopen", side_effect=AssertionError("fetch")):
            digest = self.submit(text, "html")["digestion"]
        output = json.dumps(digest)
        self.assertNotIn('raise(', output)
        self.assertNotIn("https://invalid.test", output)
        self.assertEqual(digest["coverage"]["exclusions"]["html_hidden_regions"], 2)
        self.assertIn("declared_direction", {i["category"] for i in digest["items"]})
        self.assertTrue(digest["coverage"]["gaps"])

    def test_python_symbols_bodies_and_imports_never_executed(self) -> None:
        text = 'import nonexistent\nraise RuntimeError("never run")\ndef useful():\n    return 7\nclass Example:\n    pass\n'
        digest = self.submit(text, "python", "code.py")["digestion"]
        self.assertEqual([i["category"] for i in digest["items"]], ["python_symbol", "python_symbol"])
        self.assertTrue(any("nonexistent" in g["observation"] for g in digest["residue"]["items"]))
        self.assertFalse(digest["coverage"]["execution"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.submit('value = "\\invalid escape"\n', "python")
        self.assertEqual(caught, [])

    def test_pure_contract_no_persistence_and_hash_verification(self) -> None:
        raw = b"Goal: reuse"
        reference = MaterialReference("text", "source", hashlib.sha256(raw).hexdigest(), "input.txt")
        digester = SuppliedMaterialDigester(raw, "input.txt", "text")
        self.assertEqual(digester.digest(reference).to_dict(), digester.digest(reference).to_dict())
        with self.assertRaises(MaterialError):
            digester.digest(MaterialReference("text", "source", "incorrect", "input.txt"))

    def test_malformed_binary_and_sensitive_content_have_visible_gaps(self) -> None:
        for text, format in (("def invalid(", "python"), ('a,b\n"unclosed', "csv"), ("a\0b", "text"),
                             ("ghp_" + "a" * 36, "text")):
            with self.subTest(format=format, text=text[:4]):
                digest = self.submit(text, format)["digestion"]
                self.assertTrue(digest["coverage"]["gaps"])
                self.assertNotIn(text, json.dumps(digest))
        payload = self.zip_payload(b"\xff")
        payload["material"].update({"name": "binary.txt", "format": "text"})
        self.assertIn("static_parse_failed", self.service.submit(payload)["digestion"]["coverage"]["exclusions"])

    def test_exact_input_and_output_caps_report_omissions(self) -> None:
        self.submit("x" * MAX_INPUT_BYTES)
        with self.assertRaises(MaterialError):
            self.submit("x" * (MAX_INPUT_BYTES + 1))
        digest = self.submit("\n".join(f"line {i}" for i in range(400)))["digestion"]
        self.assertEqual(len(digest["items"]), MAX_ITEMS)
        self.assertEqual(digest["coverage"]["observations"], MAX_OBSERVATIONS)
        self.assertEqual(digest["coverage"]["exclusions"]["observation_limit"], 400 - MAX_OBSERVATIONS)
        self.assertEqual(digest["coverage"]["exclusions"]["item_limit"], MAX_OBSERVATIONS - MAX_ITEMS)
        self.assertEqual(len(digest["residue"]["items"]), 30)
        digest = self.submit("a,b\n" + "a\n" * 1000, "csv")["digestion"]
        self.assertEqual(len(digest["coverage"]["gaps"]), 64)
        self.assertGreater(digest["coverage"]["exclusions"]["gap_reference_limit"], 0)

    def test_invalid_submission_fields_fail_without_persistence(self) -> None:
        examples = [
            {"material": None}, {"schema_version": True}, {"approved": True},
            {"material": {"name": "x", "format": "pdf", "text": "x"}},
            {"material": {"name": "x", "format": "text", "base64": "!"}},
            {"material": {"name": "x", "format": "text", "text": "x", "base64": "eA=="}},
            {"material": {"name": "x", "format": "zip", "text": "x"}},
            {"material": {"name": "", "format": "text", "text": "x"}},
        ]
        for change in examples:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.service.submit({**self.payload(), **change})
        self.assertEqual(self.service.list()["total"], 0)

    def test_zip_mixed_formats_provenance_no_extraction_or_nested_processing(self) -> None:
        raw = self.archive([("notes.md", b"# Topic\nGoal: safe"),
                            ("table.csv", b"name,direction\none,reuse"),
                            ("page.html", b"<p>text</p>"), ("code.py", b"def f(): pass"),
                            ("text.txt", b"plain text"), ("image.bin", b"\x00"),
                            ("nested.zip", b"not traversed")])
        with patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extract")), \
             patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extractall")):
            receipt = self.service.submit(self.zip_payload(raw))
        digest = receipt["digestion"]
        self.assertEqual(digest["coverage"]["files_read"], 5)
        self.assertEqual(digest["coverage"]["exclusions"]["unsupported_or_nested_container"], 2)
        self.assertTrue(all(f["container_sha256"] == hashlib.sha256(raw).hexdigest() for f in digest["file_evidence"]))
        self.assertEqual({f["path"] for f in digest["file_evidence"]}, {"notes.md", "table.csv", "page.html", "code.py", "text.txt"})
        self.assertFalse((self.root / "notes.md").exists())
        self.assertNotIn("base64", receipt["digestion"])
        self.assertNotIn("base64", receipt)
        self.assertNotIn("material", receipt)

    def test_zip_unsafe_paths_duplicates_and_symlinks_refused_atomically(self) -> None:
        for name in ("../escape.txt", "/absolute.txt", "C:/file.txt", "a//b.txt",
                     "a/./b.txt", "file.txt:ads", "NUL.txt", "a./b.txt"):
            with self.subTest(name=name):
                with self.assertRaises(MaterialError):
                    self.service.submit(self.zip_payload(self.archive([(name, b"safe")])))
        # ZipInfo normalizes these on Windows during writing; craft the on-wire names.
        original = self.archive([("a_b.txt", b"safe")])
        for name in (b"a\\b.txt", b"a\x00b.txt"):
            with self.assertRaises(MaterialError):
                self.service.submit(self.zip_payload(original.replace(b"a_b.txt", name)))
        link = zipfile.ZipInfo("link.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in ([("a.txt", b"a"), ("A.txt", b"b")], [(link, b"target")]):
            with self.assertRaises(MaterialError):
                self.service.submit(self.zip_payload(self.archive(entries)))
        self.assertEqual(self.service.list()["total"], 0)

    def test_zip_size_member_ratio_compression_and_corruption_limits(self) -> None:
        bad = [
            b"not a zip",
            self.archive([(f"{i}.txt", b"a") for i in range(MAX_MEMBERS + 1)]),
            self.archive([("bomb.txt", b"x" * (MAX_INPUT_BYTES + 1))], zipfile.ZIP_DEFLATED),
            self.archive([("ratio.txt", b"x" * 20000)], zipfile.ZIP_DEFLATED),
            self.archive([("large.txt", b"x" * 100)], zipfile.ZIP_BZIP2),
            self.archive([(f"{i}.txt", bytes(range(256)) * 100) for i in range(6)], zipfile.ZIP_DEFLATED),
        ]
        encrypted = bytearray(self.archive([("a.txt", b"content")]))
        central = encrypted.index(b"PK\x01\x02")
        encrypted[central + 8] |= 1
        bad.append(bytes(encrypted))
        corrupt = bytearray(self.archive([("a.txt", b"content")]))
        corrupt[corrupt.index(b"content")] ^= 1
        bad.append(bytes(corrupt))
        for raw in bad:
            with self.subTest(length=len(raw)):
                with self.assertRaises(MaterialError):
                    self.service.submit(self.zip_payload(raw))
        self.assertEqual(self.service.list()["total"], 0)
        exact_members = self.archive([(f"{i}.txt", b"a") for i in range(MAX_MEMBERS)])
        self.assertEqual(self.service.submit(self.zip_payload(exact_members))["digestion"]["coverage"]["files_read"], MAX_MEMBERS)
        exact_total = self.archive([(f"{i}.txt", bytes(range(256)) * 128) for i in range(4)],
                                   zipfile.ZIP_DEFLATED)
        digest = self.service.submit(self.zip_payload(exact_total))["digestion"]
        self.assertEqual(sum(f["size_bytes"] for f in digest["file_evidence"]), 128 * 1024)
        self.assertEqual(len(digest["file_evidence"]), 4)

    def test_cli_ingest_and_shared_json_submit_export(self) -> None:
        path = self.root / "explicit.py"
        path.write_text("def f(): pass\n", encoding="utf-8")
        args = ["--data-dir", str(self.root / "cli-runtime"), "--factory-root", str(self.root / "missing")]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["phone-home", "ingest", str(path), "--target", "f"]), 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["digestion"]["material"]["identity"], str(path))
        self.assertTrue(receipt["review"]["ingested"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["phone-home", "intake", "export", receipt["id"]]), 0)
        self.assertEqual(json.loads(output.getvalue()), receipt)
        request = self.root / "material.json"
        request.write_text(json.dumps(self.payload()), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ["phone-home", "submit", "--file", str(request)]), 0)
        path.write_bytes(b"x" * (MAX_INPUT_BYTES + 1))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["phone-home", "ingest", str(path)]), 1)

    def test_existing_loopback_endpoint_accepts_material_once(self) -> None:
        workbench = ControlPlaneWorkbench(self.root / "missing", self.root / "network", self.root / "api-runtime")
        server = serve_control_plane(port=0, workbench=workbench)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/phone-home/submissions"
        request = urllib.request.Request(url, json.dumps(self.payload()).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            receipt = json.load(response)
        self.assertTrue(receipt["review"]["ingested"])
        with urllib.request.urlopen(url + "?id=" + receipt["id"]) as response:
            self.assertEqual(json.load(response), receipt)


if __name__ == "__main__":
    unittest.main()
