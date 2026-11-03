"""Package smoke checks from unrelated working directories and isolated installs."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
import venv
import zipfile

import test_phone_home as fixtures
import build_material_core
import release


class TestPhoneHomePackage(unittest.TestCase):
    setUp = fixtures.TestPhoneHome.setUp

    def run_command(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(args, cwd=cwd or self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_public_base_install_without_core_or_credentials(self) -> None:
        built = release.build_release(self.root / "base-dist")
        self.assertIsNone(built["material_core"])
        standard = self.root / "base-standard"
        self.run_command([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                          "--no-build-isolation", "--wheel-dir", str(standard), built["sdist"]])
        for index, wheel in enumerate((Path(built["wheel"]), next(standard.glob("*.whl")))):
            environment = self.root / f"base-env-{index}"
            venv.EnvBuilder(with_pip=True).create(environment)
            scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
            python = scripts / ("python.exe" if sys.platform == "win32" else "python")
            with zipfile.ZipFile(wheel) as archive:
                metadata = archive.read("devnet_control_plane-0.1.0.dist-info/METADATA").decode()
                requirement = next(line for line in metadata.splitlines()
                                   if line.startswith("Requires-Dist: material-core"))
                self.assertIn(release.MATERIAL_CORE_COMMIT, requirement)
                self.assertIn('extra == "material"', requirement)
            self.run_command([str(python), "-m", "pip", "install", "--no-index", str(wheel)])
            self.run_command([str(python), "-m", "pip", "check"])
            self.run_command([str(python), "-I", "-c",
                              "import importlib.util; assert importlib.util.find_spec('material_core') is None; "
                              "from control_plane.fabric import FabricIndex; "
                              "from control_plane.mcp_server import tool_contracts; assert tool_contracts(); "
                              "from control_plane.ui import ControlPlaneWorkbench; "
                              "from control_plane.phone_home import validate_submission; "
                              "from control_plane.material_capability import MaterialCapabilityError; "
                              "\ntry: validate_submission({'kind':'material','material':{}})\n"
                              "except MaterialCapabilityError as e:\n"
                              " assert e.status == 503; assert '[material]' in str(e)\n"
                              "else: raise AssertionError('material must fail, not be discarded')"])
            for alias in ("devnet", "devnet-control-plane"):
                executable = scripts / (alias + (".exe" if sys.platform == "win32" else ""))
                self.run_command([str(executable), "--version"])
                self.run_command([str(executable), "--help"])
            probe = (
                "from control_plane.ui import ControlPlaneWorkbench, serve_control_plane; "
                "from pathlib import Path; import threading,urllib.request,json,urllib.error; "
                f"wb=ControlPlaneWorkbench(Path({str(self.factory)!r}),Path({str(self.network)!r}),Path({str(self.data)!r})); "
                "s=serve_control_plane(port=0,workbench=wb); t=threading.Thread(target=s.serve_forever); t.start(); "
                "base=f'http://127.0.0.1:{s.server_port}'; "
                "\ntry:\n"
                " assert json.load(urllib.request.urlopen(base+'/api/health'))['ok']\n"
                " assert json.load(urllib.request.urlopen(base+'/api/phone-home/check?q=sqlite'))['decision_ladder']\n"
                " before=wb.phone_home.list()\n"
                " req=urllib.request.Request(base+'/api/phone-home/submissions', b'{\"kind\":\"material\",\"material\":{}}',"
                " {'Content-Type':'application/json'},method='POST')\n"
                " try: urllib.request.urlopen(req)\n"
                " except urllib.error.HTTPError as e:\n"
                "  assert e.code==503; assert '[material]' in json.load(e)['error']\n"
                " else: raise AssertionError('expected explicit refusal')\n"
                " assert wb.phone_home.list()==before\n"
                "finally: s.shutdown(); s.server_close(); t.join()\n"
            )
            self.run_command([str(python), "-I", "-c", probe])

    def test_wheel_and_sdist_installed_entrypoints_registry_and_api(self) -> None:
        core_dir = self.root / "material-core"
        core = build_material_core.build_release(core_dir)
        built = release.build_release(self.root / "dist", Path(core["wheel"]))
        with zipfile.ZipFile(built["wheel"]) as archive:
            self.assertIn("control_plane/registry/interaction_frames.json", archive.namelist())
            self.assertNotIn("material_core/__init__.py", archive.namelist())
            metadata = archive.read("devnet_control_plane-0.1.0.dist-info/METADATA").decode()
            self.assertIn("Provides-Extra: mcp", metadata)
            self.assertIn(f"Requires-Dist: {release.MATERIAL_CORE_REQUIREMENT}", metadata)
        manifest = json.loads(Path(built["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["material_core_artifact"]["sha256"], core["artifacts"][0]["sha256"])
        with tarfile.open(built["sdist"]) as archive:
            self.assertTrue(any(n.endswith("/registry/interaction_frames.json") for n in archive.getnames()))
            self.assertFalse(any("/material_core/" in n for n in archive.getnames()))
        # Also build the declared setuptools path from the sdist, without network isolation.
        wheels = self.root / "sdist-wheel"
        wheels.mkdir()
        self.run_command([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                          "--no-index", "--wheel-dir", str(wheels), built["sdist"]])
        artifacts = [Path(built["wheel"]), next(wheels.glob("*.whl"))]
        for index, wheel in enumerate(artifacts):
            with self.subTest(artifact=wheel.name, builder=index):
                env = self.root / f"clean-env-{index}"
                venv.EnvBuilder(with_pip=True).create(env)
                scripts = env / ("Scripts" if sys.platform == "win32" else "bin")
                python = scripts / ("python.exe" if sys.platform == "win32" else "python")
                self.run_command([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)])
                missing = subprocess.run(
                    [str(python), "-c", "import control_plane.material_ingestion"],
                    cwd=self.root, capture_output=True, text=True, timeout=30,
                    env={**os.environ, "PYTHONPATH": ""},
                )
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn("Material capability is not installed", missing.stderr)
                self.assertIn("devnet-control-plane[material]", missing.stderr)
                self.run_command([str(python), "-m", "pip", "install", "--no-index",
                                  str(core["wheel"])])
                self.run_command([str(python), "-m", "pip", "check"])
                core_version = self.run_command([
                    str(python), "-c",
                    "from importlib.metadata import version; "
                    "assert version('material-core') == '0.1.0'; "
                    "import control_plane.material_ingestion",
                ])
                for alias in ("devnet", "devnet-control-plane"):
                    cli = scripts / (alias + (".exe" if sys.platform == "win32" else ""))
                    self.assertIn("devnet 0.1.0", self.run_command([str(cli), "--version"]).stdout)
                    self.run_command([str(cli), "--help"])
                probe = (
                    "from material_core import __version__, digest_material; "
                    "assert __version__ == '0.1.0'; "
                    "assert digest_material(b'Goal: reuse',name='note.txt',format='text').material.revision; "
                    "from control_plane import REGISTRY_PATH; assert REGISTRY_PATH.is_file(); "
                    "from control_plane.ui import ControlPlaneWorkbench, serve_control_plane; "
                    "from pathlib import Path; import urllib.request, threading, json; "
                    f"wb=ControlPlaneWorkbench(Path({str(self.factory)!r}),Path({str(self.network)!r}),Path({str(self.data)!r})); "
                    "server=serve_control_plane(port=0,workbench=wb); "
                    "thread=threading.Thread(target=server.serve_forever); thread.start(); "
                    "base=f'http://127.0.0.1:{server.server_port}'; "
                    "assert json.load(urllib.request.urlopen(base+'/api/health'))['ok']; "
                    "assert json.load(urllib.request.urlopen(base+'/api/phone-home/check?q=sqlite'))['decision_ladder']['stopped_at']==1; "
                    f"request=urllib.request.Request(base+'/api/phone-home/submissions',json.dumps({self.payload!r}).encode(),"
                    "{'Content-Type':'application/json'},method='POST'); "
                    "assert json.load(urllib.request.urlopen(request))['status']=='provisional'; "
                    "server.shutdown(); server.server_close(); thread.join()"
                )
                self.run_command([str(python), "-c", probe])
                result = self.run_command([str(python), "-m", "control_plane.cli",
                                           "--factory-root", str(self.factory), "--network-root", str(self.network),
                                           "--data-dir", str(self.data), "phone-home", "check", "sqlite"])
                self.assertIn("decision_ladder", result.stdout)
                material_file = self.root / f"supplied-{index}.json"
                material_file.write_text('{"name":["fixture"],"direction":"reuse"}', encoding="utf-8")
                ingested = self.run_command([str(python), "-m", "control_plane.cli",
                                             "--factory-root", str(self.factory),
                                             "--data-dir", str(self.data), "phone-home", "ingest",
                                             str(material_file)])
                receipt = json.loads(ingested.stdout)
                self.assertTrue(receipt["review"]["ingested"])
                self.assertFalse(receipt["review"]["acceptance_required"])
                self.assertEqual(receipt["digestion"]["material"]["kind"], "json")
                self.assertTrue({item["category"] for item in receipt["digestion"]["items"]}
                                <= {"json_object", "json_array", "json_value"})

    def test_release_builder_rejects_missing_or_incompatible_core_wheel(self) -> None:
        with self.assertRaises(FileNotFoundError):
            release.verify_material_core_wheel(self.root / "missing.whl")
        wrong = self.root / "material_core-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(wrong, "w") as archive:
            archive.writestr(
                "material_core-0.2.0.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: material-core\nVersion: 0.2.0\n\n",
            )
            for name in ("material_core/__init__.py", "material_core/contract.py",
                         "material_core/safety.py", "material_core/supplied.py"):
                archive.writestr(name, b"")
        with self.assertRaisesRegex(ValueError, "requires material-core==0.1.0"):
            release.build_release(self.root / "dncp", wrong)

    def test_editable_dncp_install_uses_local_exact_core_wheel(self) -> None:
        core_dir = self.root / "material-core"
        core = build_material_core.build_release(core_dir)
        environment = self.root / "editable-env"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        self.run_command([str(python), "-m", "pip", "install", "--no-index", str(core["wheel"])])
        self.run_command([
            str(python), "-m", "pip", "install", "--no-index", "--no-build-isolation",
            "--no-deps", "-e", str(Path(__file__).resolve().parents[1]),
        ])
        self.run_command([
            str(python), "-c",
            "from importlib.metadata import version; "
            "assert version('material-core') == '0.1.0'; "
            "import control_plane.material_ingestion",
        ])


if __name__ == "__main__":
    unittest.main()
