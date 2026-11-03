"""Independent build/install checks for the material-core distribution."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile

import build_material_core
import release


class TestMaterialCorePackage(unittest.TestCase):
    def test_isolated_wheel_and_sdist_identity_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = build_material_core.build_release(root / "wheelhouse")
            wheel = Path(artifacts["wheel"])
            sdist = Path(artifacts["sdist"])
            manifest = json.loads(Path(artifacts["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "material-core")
            self.assertEqual(manifest["version"], "0.1.0")
            self.assertEqual(manifest["source_commit"], release.MATERIAL_CORE_COMMIT)
            self.assertEqual(len(manifest["artifacts"]), 2)

            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                metadata = archive.read("material_core-0.1.0.dist-info/METADATA").decode("utf-8")
                self.assertIn("Name: material-core", metadata)
                self.assertIn("Version: 0.1.0", metadata)
                self.assertNotIn("Requires-Dist:", metadata)
                self.assertIn("material_core/supplied.py", names)
                self.assertFalse(any(name.startswith("control_plane/") for name in names))
            with tarfile.open(sdist, "r:gz") as archive:
                names = archive.getnames()
                self.assertTrue(any(name.endswith("/pyproject.toml") for name in names))
                self.assertTrue(any(name.endswith("/supplied.py") for name in names))
                self.assertFalse(any("control_plane" in name for name in names))

            environment = root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
            python = scripts / ("python.exe" if sys.platform == "win32" else "python")
            subprocess.run(
                [str(python), "-m", "pip", "install", "--no-index", str(wheel)],
                cwd=root, check=True, capture_output=True, timeout=120,
            )
            result = subprocess.run(
                [str(python), "-c",
                 "from importlib.metadata import version; "
                 "assert version('material-core') == '0.1.0'; "
                 "import material_core; "
                 "assert material_core.__version__ == '0.1.0'; "
                 "assert 'control_plane' not in __import__('sys').modules; "
                 "assert material_core.digest_material(b'Goal: reuse', name='n.txt', format='text').items"],
                cwd=root, env={**os.environ, "PYTHONPATH": ""},
                check=True, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            from control_plane.material_capability import FORMATS
            from material_core import FORMATS as core_formats
            self.assertEqual(FORMATS, core_formats)
            manifest_path = Path(artifacts["manifest"])
            manifest["source_commit"] = "0" * 40
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable source pin"):
                release.verify_material_core_wheel(wheel)
            manifest["source_commit"] = release.MATERIAL_CORE_COMMIT
            manifest["artifacts"][0]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                release.verify_material_core_wheel(wheel)

    def test_dncp_consumer_rejects_an_incompatible_installed_core_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (
            "from unittest.mock import patch; "
            "from types import SimpleNamespace; "
            "d=SimpleNamespace(version='0.2.0',read_text=lambda n: '{}'); "
            "p=patch('control_plane.material_capability.distribution', return_value=d); p.start(); "
            "import control_plane.material_ingestion"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DNCP requires material-core==0.1.0", result.stderr)


if __name__ == "__main__":
    unittest.main()
