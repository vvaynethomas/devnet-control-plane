"""Network registry reader: synthetic entries only."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_plane.cli import main
from control_plane.network_registry import (
    NetworkRegistryError, find_registry_root, get_entry, list_entries, load_entries,
)


def entry(entry_id: str, **overrides: object) -> dict:
    base = {
        "id": entry_id, "kind": "product", "title": "Example", "status": "seed", "home": None,
        "initialized_by": "product-incubator", "initialized_on": entry_id[:10], "origin": "test",
    }
    base.update(overrides)
    return base


class NetworkRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "registry"
        (self.root / "entries").mkdir(parents=True)

    def write(self, name: str, payload: object) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (self.root / "entries" / name).write_text(text, encoding="utf-8")

    def test_lists_and_filters_entries(self) -> None:
        self.write("2026-01-01-alpha.json", entry("2026-01-01-alpha"))
        self.write("2026-01-02-beta.json", entry("2026-01-02-beta", kind="tool", status="handed-off", home="https://example.test/beta"))
        self.assertEqual(list_entries(self.root)["count"], 2)
        tools = list_entries(self.root, kind="tool")
        self.assertEqual([e["id"] for e in tools["entries"]], ["2026-01-02-beta"])
        self.assertEqual(tools["total"], 2)
        self.assertEqual(list_entries(self.root, status="seed")["count"], 1)
        self.assertEqual(list_entries(self.root, initialized_by="someone-else")["count"], 0)
        self.assertEqual(get_entry(self.root, "2026-01-02-beta")["home"], "https://example.test/beta")

    def test_bad_files_are_skipped_and_reported(self) -> None:
        self.write("2026-01-01-alpha.json", entry("2026-01-01-alpha"))
        self.write("2026-01-03-broken.json", "{not json")
        self.write("2026-01-04-partial.json", {"id": "2026-01-04-partial"})
        self.write("2026-01-05-renamed.json", entry("2026-01-05-other"))
        self.write("2026-01-06-list.json", [1, 2])
        loaded = load_entries(self.root)
        self.assertEqual([e["id"] for e in loaded["entries"]], ["2026-01-01-alpha"])
        self.assertEqual(
            sorted(s["file"] for s in loaded["skipped"]),
            ["2026-01-03-broken.json", "2026-01-04-partial.json", "2026-01-05-renamed.json", "2026-01-06-list.json"],
        )

    def test_missing_registry_and_unknown_id_raise(self) -> None:
        with self.assertRaises(NetworkRegistryError):
            load_entries(Path(self.tmp.name) / "absent")
        with self.assertRaises(NetworkRegistryError):
            get_entry(self.root, "2026-01-09-none")

    def test_root_resolution_order(self) -> None:
        network = Path(self.tmp.name) / "net"
        default = network / "devnet" / "network-registry" / "main"
        (default / "entries").mkdir(parents=True)
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("DEVNET_REGISTRY_ROOT", None)
            self.assertEqual(find_registry_root(network), default)
            self.assertEqual(find_registry_root(network, self.root), self.root.resolve())
            env["DEVNET_REGISTRY_ROOT"] = str(self.root)
            self.assertEqual(find_registry_root(network), self.root.resolve())

    def test_cli_list_and_show(self) -> None:
        self.write("2026-01-01-alpha.json", entry("2026-01-01-alpha"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["registry", "--registry-root", str(self.root), "list", "--kind", "product"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["count"], 1)
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["registry", "--registry-root", str(self.root), "show", "2026-01-01-alpha"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["title"], "Example")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main(["registry", "--registry-root", str(self.root), "show", "2026-01-09-none"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
