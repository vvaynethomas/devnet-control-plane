"""Active module provenance and shadow isolation, without external access."""

from importlib.metadata import distribution, PackageNotFoundError
import json
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
import tempfile
import unittest
from unittest.mock import patch
import importlib.util

from control_plane.material_capability import (
    CORE_COMMIT, CORE_URL, CORE_VERSION, MaterialCapabilityError, require_material_core,
)
from control_plane.material_pins import UTILITY_COMMIT

try:
    _core_dist = distribution("material-core")
    _utility_dist = distribution("utility-chest-credential-patterns")
    _core_url = json.loads(_core_dist.read_text("direct_url.json") or "{}")
    _utility_url = json.loads(_utility_dist.read_text("direct_url.json") or "{}")
    HAS_CORE = (
        _core_dist.version == CORE_VERSION
        and _core_url.get("vcs_info", {}).get("commit_id") == CORE_COMMIT
        and _utility_url.get("vcs_info", {}).get("commit_id") == UTILITY_COMMIT
    )
except PackageNotFoundError:
    HAS_CORE = False


class TestMaterialProvenance(unittest.TestCase):
    def tearDown(self):
        require_material_core.cache_clear()

    def test_same_version_wrong_source_refused_before_execution(self):
        fake = SimpleNamespace(version=CORE_VERSION, read_text=lambda name: json.dumps(
            {"url": "https://example.invalid/other", "vcs_info": {"commit_id": CORE_COMMIT}}
        ))
        with patch("control_plane.material_capability.distribution", return_value=fake):
            require_material_core.cache_clear()
            with self.assertRaisesRegex(MaterialCapabilityError, "verified source provenance"):
                require_material_core()

    def test_unverified_same_version_local_install_refused(self):
        fake = SimpleNamespace(version=CORE_VERSION, read_text=lambda name: "{}")
        with patch("control_plane.material_capability.distribution", return_value=fake):
            require_material_core.cache_clear()
            with self.assertRaises(MaterialCapabilityError):
                require_material_core()

    def test_same_version_wrong_source_utility_is_refused(self):
        from control_plane.material_pins import UTILITY_VERSION, UTILITY_COMMIT
        fake_core = SimpleNamespace(version=CORE_VERSION)
        fake_utility = SimpleNamespace(version=UTILITY_VERSION, read_text=lambda name: json.dumps(
            {"url": "https://example.invalid/unrelated-utility", "vcs_info": {"commit_id": UTILITY_COMMIT}}
        ))
        with patch("control_plane.material_capability.distribution",
                   side_effect=lambda name: fake_core if name == "material-core" else fake_utility):
            require_material_core.cache_clear()
            with self.assertRaises(MaterialCapabilityError):
                require_material_core()

    @unittest.skipUnless(HAS_CORE,
                         "Requires the optional pinned material distribution to exercise real owned files")
    def test_path_and_preloaded_shadow_never_execute(self):
        installed = distribution("material-core")
        direct = json.loads(installed.read_text("direct_url.json"))
        self.assertEqual(direct["vcs_info"]["commit_id"], CORE_COMMIT)
        with tempfile.TemporaryDirectory() as temporary:
            shadow = Path(temporary) / "material_core"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("raise AssertionError('shadow executed')", encoding="utf-8")
            utility_shadow = Path(temporary) / "credential_patterns"
            utility_shadow.mkdir()
            (utility_shadow / "__init__.py").write_text("raise AssertionError('utility shadow executed')", encoding="utf-8")
            hostile = ModuleType("material_core")
            hostile.__version__ = CORE_VERSION
            hostile.digest_material = lambda *a, **k: (_ for _ in ()).throw(AssertionError("preloaded shadow"))
            hostile_utility = ModuleType("credential_patterns")
            with patch.object(sys, "path", [temporary, *sys.path]), patch.dict(sys.modules, {
                "material_core": hostile, "credential_patterns": hostile_utility,
            }):
                require_material_core.cache_clear()
                core = require_material_core()
                self.assertNotEqual(core.__name__, "material_core")
                self.assertTrue(core.digest_material(b"Goal: reuse", name="n.txt", format="text").items)
                self.assertIs(sys.modules["credential_patterns"], hostile_utility)
