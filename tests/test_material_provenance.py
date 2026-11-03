"""Active module provenance and shadow isolation, without external access."""

from importlib.metadata import distribution
import json
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
import tempfile
import unittest
from unittest.mock import patch

from control_plane.material_capability import (
    CORE_COMMIT, CORE_URL, MaterialCapabilityError, require_material_core,
)


class TestMaterialProvenance(unittest.TestCase):
    def tearDown(self):
        require_material_core.cache_clear()

    def test_same_version_wrong_source_refused_before_execution(self):
        fake = SimpleNamespace(version="0.1.0", read_text=lambda name: json.dumps(
            {"url": "https://example.invalid/other", "vcs_info": {"commit_id": CORE_COMMIT}}
        ))
        with patch("control_plane.material_capability.distribution", return_value=fake):
            require_material_core.cache_clear()
            with self.assertRaisesRegex(MaterialCapabilityError, "verified source provenance"):
                require_material_core()

    def test_unverified_same_version_local_install_refused(self):
        fake = SimpleNamespace(version="0.1.0", read_text=lambda name: "{}")
        with patch("control_plane.material_capability.distribution", return_value=fake):
            require_material_core.cache_clear()
            with self.assertRaises(MaterialCapabilityError):
                require_material_core()

    def test_path_and_preloaded_shadow_never_execute(self):
        installed = distribution("material-core")
        direct = json.loads(installed.read_text("direct_url.json"))
        self.assertEqual(direct["vcs_info"]["commit_id"], CORE_COMMIT)
        with tempfile.TemporaryDirectory() as temporary:
            shadow = Path(temporary) / "material_core"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("raise AssertionError('shadow executed')", encoding="utf-8")
            hostile = ModuleType("material_core")
            hostile.__version__ = "0.1.0"
            hostile.digest_material = lambda *a, **k: (_ for _ in ()).throw(AssertionError("preloaded shadow"))
            with patch.object(sys, "path", [temporary, *sys.path]), patch.dict(sys.modules, {"material_core": hostile}):
                require_material_core.cache_clear()
                core = require_material_core()
                self.assertNotEqual(core.__name__, "material_core")
                self.assertTrue(core.digest_material(b"Goal: reuse", name="n.txt", format="text").items)
