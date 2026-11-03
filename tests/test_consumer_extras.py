"""Authenticated isolated installation matrix for both optional consumers."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
import os

import release
from control_plane.material_pins import HUB_VERSION, HUB_COMMIT


@unittest.skipUnless(os.environ.get("DNCP_PRIVATE_INTEGRATION") == "1",
                     "Set DNCP_PRIVATE_INTEGRATION=1 for private Git dependency installation matrix")
class TestConsumerExtras(unittest.TestCase):
    def test_each_extra_and_both_with_standard_and_custom_wheels(self):
        tests = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = release.build_release(root / "custom")

            def run(args):
                result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                 "--no-build-isolation", "--wheel-dir", str(root / "standard"), built["sdist"]])
            for builder, wheel in enumerate((Path(built["wheel"]), next((root / "standard").glob("*.whl")))):
                for extras in ("material", "conversation-hub", "material,conversation-hub"):
                    with self.subTest(builder=builder, extras=extras):
                        environment = root / f"env-{builder}-{extras.replace(',', '-')}"
                        venv.EnvBuilder(with_pip=True).create(environment)
                        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
                        run([str(python), "-m", "pip", "install", f"{wheel}[{extras}]"])
                        run([str(python), "-m", "pip", "check"])
                        material = "material" in extras
                        hub = "conversation-hub" in extras
                        script = (
                            "import importlib.util,json,sys,unittest; from importlib.metadata import distribution; "
                            f"assert (importlib.util.find_spec('material_core') is not None)=={material}; "
                            f"assert (importlib.util.find_spec('conversation_hub') is not None)=={hub}; "
                            f"sys.path.insert(0,{str(tests)!r}); "
                        )
                        if material:
                            script += (
                                "from control_plane.material_capability import require_material_core,CORE_COMMIT; "
                                "assert json.loads(distribution('material-core').read_text('direct_url.json'))['vcs_info']['commit_id']==CORE_COMMIT; "
                                "assert require_material_core().digest_material(b'Goal: reuse',name='n.txt',format='text').items; "
                                "suite=unittest.defaultTestLoader.loadTestsFromName('test_material_provenance'); "
                                "assert unittest.TextTestRunner().run(suite).wasSuccessful(); "
                            )
                        else:
                            script += (
                                "from control_plane.material_capability import require_material_core,MaterialCapabilityError; "
                                "\ntry: require_material_core()\n"
                                "except MaterialCapabilityError as e: assert '[material]' in str(e)\n"
                                "else: raise AssertionError('missing material accepted')\n"
                            )
                        if hub:
                            script += (
                                "from control_plane.conversation_library import _configured_snapshot_reader; "
                                f"reader,info=_configured_snapshot_reader(); assert info['version']=={HUB_VERSION!r}; "
                                f"assert info['revision']=={HUB_COMMIT!r}; "
                                "suite=unittest.defaultTestLoader.loadTestsFromName("
                                "'test_conversation_library.ConversationLibraryTests.test_pinned_hub_reader_reads_synthetic_library_when_extra_is_installed'); "
                                "assert unittest.TextTestRunner().run(suite).wasSuccessful(); "
                            )
                        else:
                            script += (
                                "from control_plane.conversation_library import _configured_snapshot_reader,ConversationLibraryError; "
                                "\ntry: _configured_snapshot_reader()\n"
                                "except ConversationLibraryError as e: assert e.code=='hub_unavailable'\n"
                                "else: raise AssertionError('missing hub accepted')\n"
                            )
                        run([str(python), "-I", "-c", script])


if __name__ == "__main__":
    unittest.main()
