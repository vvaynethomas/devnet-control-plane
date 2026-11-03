"""Package smoke checks from unrelated working directories and isolated installs."""

import asyncio
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
import release


class TestPhoneHomePackage(unittest.TestCase):
    setUp = fixtures.TestPhoneHome.setUp

    def run_command(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(args, cwd=cwd or self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_wheel_and_sdist_installed_entrypoints_registry_and_api(self) -> None:
        built = release.build_release(self.root / "dist")
        with zipfile.ZipFile(built["wheel"]) as archive:
            self.assertIn("control_plane/registry/interaction_frames.json", archive.namelist())
            self.assertIn("material_core/__init__.py", archive.namelist())
            self.assertIn("material_core/supplied.py", archive.namelist())
            metadata = archive.read("devnet_control_plane-0.1.0.dist-info/METADATA").decode()
            self.assertIn("Provides-Extra: mcp", metadata)
        with tarfile.open(built["sdist"]) as archive:
            self.assertTrue(any(n.endswith("/registry/interaction_frames.json") for n in archive.getnames()))
            self.assertTrue(any(n.endswith("/material_core/supplied.py") for n in archive.getnames()))
        # Also build the declared setuptools path from the sdist, without network isolation.
        wheels = self.root / "sdist-wheel"
        wheels.mkdir()
        self.run_command([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                          "--wheel-dir", str(wheels), built["sdist"]])
        artifacts = [Path(built["wheel"]), next(wheels.glob("*.whl"))]
        for index, wheel in enumerate(artifacts):
            with self.subTest(artifact=wheel.name, builder=index):
                env = self.root / f"clean-env-{index}"
                venv.EnvBuilder(with_pip=True).create(env)
                scripts = env / ("Scripts" if sys.platform == "win32" else "bin")
                python = scripts / ("python.exe" if sys.platform == "win32" else "python")
                self.run_command([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)])
                for alias in ("devnet", "devnet-control-plane"):
                    cli = scripts / (alias + (".exe" if sys.platform == "win32" else ""))
                    self.assertIn("devnet 0.1.0", self.run_command([str(cli), "--version"]).stdout)
                    self.run_command([str(cli), "--help"])
                probe = (
                    "from material_core import digest_material; "
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
                if index == 0:
                    self.run_command([str(python), "-m", "pip", "install", "--quiet", f"{wheel}[mcp]"])
                    self.check_installed_mcp(python)

    def check_installed_mcp(self, python: Path) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def exercise() -> None:
            env = dict(os.environ)
            env.update({"PYTHONPATH": "", "FACTORY_ROOT": str(self.factory),
                        "DEV_NETWORK_ROOT": str(self.network), "DEVNET_DATA_DIR": str(self.data)})
            params = StdioServerParameters(command=str(python), args=["-m", "control_plane.cli", "mcp"],
                                           env=env, cwd=self.root)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool("phone_home_check", {"query": "sqlite"})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent["decision_ladder"]["stopped_at"], 1)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
