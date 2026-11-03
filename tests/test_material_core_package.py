"""Hermetic consumer checks; private release installation is explicitly opt-in."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from unittest.mock import patch

import build_material_core
import release


class TestMaterialCorePackage(unittest.TestCase):
    def test_runtime_artifact_pin_matches_release_gate(self):
        from control_plane.material_capability import CORE_VERSION, CORE_COMMIT, CORE_WHEEL_SHA256
        self.assertEqual(CORE_VERSION, release.MATERIAL_CORE_VERSION)
        self.assertEqual(CORE_COMMIT, release.MATERIAL_CORE_COMMIT)
        self.assertEqual(CORE_WHEEL_SHA256, release.MATERIAL_CORE_WHEEL_SHA256)

    def test_substituted_same_version_wheel_and_self_edited_manifest_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / f"material_core-{release.MATERIAL_CORE_VERSION}-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    f"material_core-{release.MATERIAL_CORE_VERSION}.dist-info/METADATA",
                    f"Metadata-Version: 2.1\nName: material-core\nVersion: {release.MATERIAL_CORE_VERSION}\n",
                )
                for name in ("__init__", "contract", "safety", "supplied"):
                    archive.writestr(f"material_core/{name}.py", "raise AssertionError('substituted code')")
            (root / "RELEASE_MANIFEST.json").write_text(json.dumps({
                "source_commit": release.MATERIAL_CORE_COMMIT,
                "artifacts": [{"filename": wheel.name,
                               "sha256": release.compute_sha256(wheel.read_bytes())}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "independently pinned producer release"):
                release.verify_material_core_wheel(wheel)

    def test_substituted_utility_wheel_is_refused(self):
        data = b"substituted utility release"
        filename = f"utility_chest_credential_patterns-{release.UTILITY_VERSION}-py3-none-any.whl"
        with self.assertRaisesRegex(ValueError, "independently pinned producer release"):
            release.verify_utility_bytes(data, filename)

    def test_installer_consumes_verified_snapshot_not_mutated_input(self):
        import install_material_core
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / f"material_core-{release.MATERIAL_CORE_VERSION}-py3-none-any.whl"
            wheel.write_bytes(b"verified byte snapshot")
            names = [f"material_core/{name}.py" for name in ("__init__", "contract", "safety", "supplied")]
            for name in names:
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"")
            metadata = root / f"material_core-{release.MATERIAL_CORE_VERSION}.dist-info"
            metadata.mkdir()
            installed = SimpleNamespace(files=[f"material_core-{release.MATERIAL_CORE_VERSION}.dist-info/METADATA"],
                                        locate_file=lambda name: root / name,
                                        read_text=lambda name: "{}")

            def verify(data, filename):
                self.assertEqual(data, b"verified byte snapshot")
                wheel.write_bytes(b"substitution after verification")
                return {"source_commit": release.MATERIAL_CORE_COMMIT,
                        "sha256": release.MATERIAL_CORE_WHEEL_SHA256,
                        "source_sha256": {name: release.compute_sha256(b"") for name in names}}

            def consume(args, **kwargs):
                self.assertEqual(Path(args[-1]).read_bytes(), b"verified byte snapshot")

            with patch.object(install_material_core, "verify_material_core_bytes", side_effect=verify), \
                    patch.object(install_material_core.subprocess, "run", side_effect=consume), \
                    patch.object(install_material_core, "distribution", return_value=installed):
                install_material_core._install_verified(
                    b"verified byte snapshot", wheel.name, verify(b"verified byte snapshot", wheel.name), "material-core")

    @unittest.skipUnless(os.environ.get("DNCP_PRIVATE_INTEGRATION") == "1",
                         "Set DNCP_PRIVATE_INTEGRATION=1 for authenticated published-wheel installation")
    def test_isolated_published_wheel_identity_and_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = build_material_core.build_release(root / "wheelhouse")
            wheel = Path(artifacts["wheel"])
            self.assertEqual(release.compute_sha256(wheel.read_bytes()), release.MATERIAL_CORE_WHEEL_SHA256)
            utility_wheel = Path(artifacts["utility_wheel"])
            offline = release.build_release(root / "dncp", wheel, utility_wheel)
            offline_manifest = json.loads(Path(offline["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(offline_manifest["material_core_artifact"]["sha256"],
                             release.MATERIAL_CORE_WHEEL_SHA256)
            self.assertEqual(offline_manifest["utility_artifact"]["sha256"],
                             release.UTILITY_WHEEL_SHA256)
            manifest = json.loads(Path(artifacts["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_commit"], release.MATERIAL_CORE_COMMIT)
            environment = root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps",
                            artifacts["utility_wheel"], str(wheel)],
                           cwd=root, check=True, capture_output=True, timeout=120)
            script = (
                "from importlib.metadata import version; import material_core,sys; "
                f"assert version('material-core') == {release.MATERIAL_CORE_VERSION!r}; "
                "assert 'control_plane' not in sys.modules; "
                "assert material_core.digest_material(b'Goal: reuse',name='n.txt',format='text').items"
            )
            subprocess.run([str(python), "-I", "-c", script], cwd=root, check=True,
                           capture_output=True, timeout=30)

    def test_dncp_consumer_rejects_an_incompatible_installed_core_version(self):
        from types import SimpleNamespace
        from control_plane.material_capability import require_material_core, MaterialCapabilityError
        fake = SimpleNamespace(version="0.2.0", read_text=lambda name: "{}")
        require_material_core.cache_clear()
        self.addCleanup(require_material_core.cache_clear)
        with patch("control_plane.material_capability.distribution", return_value=fake):
            with self.assertRaisesRegex(MaterialCapabilityError, "verified source provenance"):
                require_material_core()


if __name__ == "__main__":
    unittest.main()
