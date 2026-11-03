"""Consumer-facing material core boundary checks."""

import subprocess
import sys
import unittest
from pathlib import Path


class TestMaterialCoreBoundary(unittest.TestCase):
    def test_core_import_and_digest_need_no_dncp_services_or_runtime_io(self) -> None:
        script = r"""
import builtins
original_import = builtins.__import__
blocked = {"control_plane", "socket", "subprocess", "sqlite3"}
def guarded_import(name, *args, **kwargs):
    if name.split(".", 1)[0] in blocked:
        raise AssertionError("forbidden dependency imported: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from material_core import digest_material
def deny_open(*args, **kwargs):
    raise AssertionError("material digestion performed filesystem I/O")
builtins.open = deny_open
result = digest_material(b"Goal: reuse\nbody", name="note.txt", format="text", target="reuse")
assert result.material.revision
assert result.coverage["execution"] is False
assert result.coverage["external_requests"] is False
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
