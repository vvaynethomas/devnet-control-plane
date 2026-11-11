"""Hermetic consumer checks; private release installation is explicitly opt-in."""

import json
import os
import base64
import csv
import hashlib
import io
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
                for name in ("__init__", "contract", "conversation", "safety", "supplied"):
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

    def test_alm_wheel_is_checked_against_its_own_pins(self):
        import io
        from unittest.mock import patch

        def wheel(modules=("__init__", "lifecycle"), extra_metadata=""):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    f"alm_lifecycle_core-{release.ALM_VERSION}.dist-info/METADATA",
                    f"Metadata-Version: 2.1\nName: alm-lifecycle-core\nVersion: {release.ALM_VERSION}\n{extra_metadata}",
                )
                for name in modules:
                    archive.writestr(f"alm_lifecycle/{name}.py", "VALUE = 1\n")
            return buffer.getvalue()

        filename = f"alm_lifecycle_core-{release.ALM_VERSION}-py3-none-any.whl"
        data = wheel()
        with self.assertRaisesRegex(ValueError, "independently pinned producer release"):
            release.verify_alm_bytes(data, filename)
        with self.assertRaisesRegex(ValueError, "wheel filename"):
            release.verify_alm_bytes(data, "alm_lifecycle_core-9.9-py3-none-any.whl")
        with patch.object(release, "ALM_WHEEL_SHA256", release.compute_sha256(data)):
            artifact = release.verify_alm_bytes(data, filename)
        self.assertEqual((artifact["version"], artifact["source_commit"]), (release.ALM_VERSION, release.ALM_COMMIT))
        self.assertEqual(sorted(artifact["source_sha256"]), ["alm_lifecycle/__init__.py", "alm_lifecycle/lifecycle.py"])
        for bad, message in ((wheel(modules=("__init__",)), "missing required package modules"),
                             (wheel(extra_metadata="Requires-Dist: requests\n"), "must not declare runtime dependencies")):
            with patch.object(release, "ALM_WHEEL_SHA256", release.compute_sha256(bad)):
                with self.assertRaisesRegex(ValueError, message):
                    release.verify_alm_bytes(bad, filename)

    @unittest.skipUnless(os.environ.get("DNCP_ALM_WHEEL"),
                         "Set DNCP_ALM_WHEEL to the published alm-lifecycle-core wheel for the offline install check")
    def test_offline_alm_install_loads_and_bare_or_tampered_installs_are_refused(self):
        wheel = Path(os.environ["DNCP_ALM_WHEEL"]).resolve()
        project = Path(__file__).resolve().parents[1]
        check = (
            f"import sys; sys.path.insert(0, {str(project)!r}); from control_plane import alm_exchange as a\n"
            "try: print('loaded', a.require_alm_core().__version__)\n"
            "except a.AlmExchangeError as e: print('refused', e.code)\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def environment(name):
                venv.EnvBuilder(with_pip=True).create(root / name)
                return root / name / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

            def run(*arguments):
                result = subprocess.run([str(a) for a in arguments], cwd=root, capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout.strip()

            verified = environment("verified")
            run(verified, project / "install_alm_core.py", wheel)
            self.assertEqual(run(verified, "-c", check), f"loaded {release.ALM_VERSION}")
            bare = environment("bare")
            run(bare, "-m", "pip", "install", "--no-index", "--no-deps", wheel)
            self.assertEqual(run(bare, "-c", check), "refused capability_unverified")
            installed = Path(run(verified, "-c", "import alm_lifecycle.lifecycle as m; print(m.__file__)"))
            installed.write_bytes(installed.read_bytes() + b"# changed\n")
            self.assertEqual(run(verified, "-c", check), "refused capability_unverified")

    def test_offline_installer_ignores_shadow_pip_metadata_and_ambient_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "dncp_test_guard-1.0-py3-none-any.whl"
            source_name = "dncp_guard/__init__.py"
            sources = {source_name: b"VALUE = 'installed from verified wheel'\n"}
            dist_info = "dncp_test_guard-1.0.dist-info"
            wheel_files = {
                source_name: sources[source_name],
                f"{dist_info}/METADATA": b"Metadata-Version: 2.1\nName: dncp-test-guard\nVersion: 1.0\n",
                f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            }
            record = io.StringIO()
            writer = csv.writer(record, lineterminator="\n")
            for name, content in wheel_files.items():
                digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                writer.writerow((name, f"sha256={digest}", len(content)))
            writer.writerow((f"{dist_info}/RECORD", "", ""))
            wheel_files[f"{dist_info}/RECORD"] = record.getvalue().encode()
            with zipfile.ZipFile(wheel, "w") as archive:
                for name, content in wheel_files.items():
                    archive.writestr(name, content)

            artifact = {
                "version": "1.0",
                "source_commit": "test-commit",
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "source_sha256": {
                    name: hashlib.sha256(content).hexdigest() for name, content in sources.items()
                },
            }
            payload = root / "artifact.json"
            payload.write_text(json.dumps(artifact), encoding="utf-8")
            hostile = root / "hostile-cwd"
            shadow_pip = hostile / "pip"
            shadow_pip.mkdir(parents=True)
            marker = root / "shadow-pip-ran"
            (shadow_pip / "__main__.py").write_text(
                f"from pathlib import Path; Path({str(marker)!r}).touch()\n", encoding="utf-8",
            )
            fake_metadata = hostile / f"{dist_info}"
            fake_metadata.mkdir()
            (fake_metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: dncp-test-guard\nVersion: 0.0\n", encoding="utf-8",
            )
            target = root / "ambient-target"
            target.mkdir()
            pip_config = root / "pip.ini"
            pip_config.write_text(f"[global]\ntarget = {target}\n", encoding="utf-8")
            environment = root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            project = Path(__file__).resolve().parents[1]
            script = (
                "import json,sys; "
                f"sys.path.insert(0, {str(project)!r}); "
                "from install_material_core import _install_verified; "
                "wheel=Path(sys.argv[1]); "
                "_install_verified(wheel.read_bytes(), wheel.name, json.loads(Path(sys.argv[2]).read_text()), "
                "'dncp-test-guard')"
            )
            script = "from pathlib import Path; " + script
            env = os.environ.copy()
            env["PIP_TARGET"] = str(target)
            env["PIP_CONFIG_FILE"] = str(pip_config)
            subprocess.run(
                [str(python), "-c", script, str(wheel), str(payload)],
                cwd=hostile, env=env, check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertFalse(marker.exists())
            self.assertEqual(list(target.iterdir()), [])
            check = (
                "from importlib.metadata import distribution; "
                "from pathlib import Path; import json; "
                "d=distribution('dncp-test-guard'); "
                "assert d.version == '1.0'; "
                "assert Path(d.locate_file('dncp_guard/__init__.py')).read_text().startswith(\"VALUE = 'installed\"); "
                "assert json.loads(d.read_text('dncp_material_provenance.json'))['source_commit'] == 'test-commit'"
            )
            subprocess.run([str(python), "-I", "-c", check], cwd=hostile, check=True,
                           capture_output=True, text=True, timeout=30)
            # Installer-owned provenance must disappear with the distribution, or
            # importlib sees a version-less ghost and pip cannot reinstall it.
            clean_env = {key: value for key, value in os.environ.items()
                         if not key.upper().startswith(("PYTHON", "PIP_"))}
            clean_env["PIP_CONFIG_FILE"] = os.devnull
            subprocess.run([str(python), "-I", "-m", "pip", "uninstall", "-y", "dncp-test-guard"],
                           cwd=root, env=clean_env, check=True, capture_output=True, timeout=30)
            site_packages = environment / ("Lib/site-packages" if sys.platform == "win32" else
                                           f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
            self.assertFalse((site_packages / dist_info).exists(), "Uninstall left orphaned distribution metadata")
            subprocess.run([str(python), "-I", "-c", script, str(wheel), str(payload)],
                           cwd=root, env=clean_env, check=True, capture_output=True, timeout=120)
            subprocess.run([str(python), "-I", "-c", check], cwd=root, check=True,
                           capture_output=True, text=True, timeout=30)

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
        from control_plane.material_capability import (
            MaterialCapabilityError, clear_material_core_cache, require_material_core,
        )
        fake = SimpleNamespace(version="0.2.0", read_text=lambda name: "{}")
        clear_material_core_cache()
        self.addCleanup(clear_material_core_cache)
        with patch("control_plane.material_capability.distribution", return_value=fake):
            with self.assertRaisesRegex(MaterialCapabilityError, "verified source provenance"):
                require_material_core()


if __name__ == "__main__":
    unittest.main()
