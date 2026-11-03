"""Active module provenance and shadow isolation, without external access."""

from importlib.metadata import distribution, PackageNotFoundError
import json
import hashlib
import os
from pathlib import Path
import py_compile
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

    def test_core_and_utility_execute_captured_transitive_sources_not_pyc(self):
        from control_plane.material_pins import (
            UTILITY_SUBDIRECTORY, UTILITY_URL, UTILITY_VERSION,
        )
        from control_plane.safety import _LOCAL_SECRET_RE

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            utility_root = root / "utility"
            core_root = root / "core"
            utility_package = utility_root / "credential_patterns"
            core_package = core_root / "material_core"
            utility_package.mkdir(parents=True)
            core_package.mkdir(parents=True)

            utility_init = "from .rules import SECRET_RE\n"
            utility_rules = (
                "import re\n"
                f"SECRET_RE = re.compile({_LOCAL_SECRET_RE.pattern!r}, flags={_LOCAL_SECRET_RE.flags})\n"
            )
            (utility_package / "__init__.py").write_text(utility_init, encoding="utf-8")
            rules_path = utility_package / "rules.py"
            evil_source = "import re\nSECRET_RE = re.compile('cached-bytecode-shadow')\n"
            evil_source = evil_source.ljust(len(utility_rules))
            rules_path.write_text(evil_source, encoding="utf-8")
            cached = Path(py_compile.compile(str(rules_path), doraise=True))
            timestamp = rules_path.stat().st_mtime
            rules_path.write_text(utility_rules, encoding="utf-8")
            os.utime(rules_path, (timestamp, timestamp))
            self.assertTrue(cached.is_file())

            core_sources = {
                "__init__.py": (
                    f"__version__ = {CORE_VERSION!r}\n"
                    "from .contract import VALUE\n"
                    "from . import safety\n"
                ),
                "contract.py": "from .nested import MATERIAL_VALUE\nVALUE = MATERIAL_VALUE\n",
                "nested.py": "MATERIAL_VALUE = 'captured-core-source'\n",
                "safety.py": "from credential_patterns import SECRET_RE\n",
                "supplied.py": "from .contract import VALUE\n",
            }
            for name, source in core_sources.items():
                (core_package / name).write_text(source, encoding="utf-8")

            class PinnedDistribution:
                def __init__(self, package_root, package_name, version, direct_url, source_names):
                    self.version = version
                    self.root = package_root
                    self.files = [Path(f"{package_name}/{name}") for name in source_names]
                    self.direct_url = direct_url

                def read_text(self, name):
                    return json.dumps(self.direct_url) if name == "direct_url.json" else "{}"

                def locate_file(self, name):
                    return self.root / name

            utility_direct = {
                "url": f"{UTILITY_URL}.git",
                "vcs_info": {"vcs": "git", "commit_id": UTILITY_COMMIT},
                "subdirectory": UTILITY_SUBDIRECTORY,
            }
            core_direct = {
                "url": f"{CORE_URL}.git",
                "vcs_info": {"vcs": "git", "commit_id": CORE_COMMIT},
            }
            distributions = {
                "utility-chest-credential-patterns": PinnedDistribution(
                    utility_root, "credential_patterns", UTILITY_VERSION, utility_direct,
                    ("__init__.py", "rules.py"),
                ),
                "material-core": PinnedDistribution(
                    core_root, "material_core", CORE_VERSION, core_direct, tuple(core_sources),
                ),
            }
            with patch("control_plane.material_capability.distribution",
                       side_effect=distributions.__getitem__):
                require_material_core.cache_clear()
                loaded = require_material_core()

            self.assertEqual(loaded.VALUE, "captured-core-source")
            self.assertEqual(loaded.safety.SECRET_RE.pattern, _LOCAL_SECRET_RE.pattern)
            self.assertIsNot(loaded.safety.SECRET_RE, _LOCAL_SECRET_RE)

    def test_offline_core_and_utility_snapshots_validate_before_execution(self):
        from control_plane.material_pins import (
            CORE_WHEEL_SHA256, UTILITY_VERSION, UTILITY_WHEEL_SHA256,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            utility_root = root / "utility"
            core_root = root / "core"
            utility_package = utility_root / "credential_patterns"
            core_package = core_root / "material_core"
            utility_package.mkdir(parents=True)
            core_package.mkdir(parents=True)
            marker = root / "utility-executed"
            utility_content = (
                f"from pathlib import Path; Path({str(marker)!r}).touch()\n"
            ).encode()
            core_contents = {
                "__init__.py": f"__version__ = {CORE_VERSION!r}\n".encode(),
                "contract.py": b"EXPECTED_CORE_SOURCE = True\n",
                "safety.py": b"",
                "supplied.py": b"",
            }
            (utility_package / "__init__.py").write_bytes(utility_content)
            for name, content in core_contents.items():
                (core_package / name).write_bytes(content)

            def distribution_evidence(package, contents, commit, wheel_hash, direct):
                hashes = {
                    f"{package}/{name}": hashlib.sha256(content).hexdigest()
                    for name, content in contents.items()
                }
                return {
                    "source_commit": commit,
                    "artifact_sha256": wheel_hash,
                    "source_sha256": hashes,
                    "direct_url": direct,
                }

            utility_direct = {
                "url": "file:///verified-utility.whl",
                "archive_info": {"hashes": {"sha256": UTILITY_WHEEL_SHA256}},
            }
            core_direct = {
                "url": "file:///verified-core.whl",
                "archive_info": {"hashes": {"sha256": CORE_WHEEL_SHA256}},
            }
            utility_evidence = distribution_evidence(
                "credential_patterns", {"__init__.py": utility_content},
                UTILITY_COMMIT, UTILITY_WHEEL_SHA256, utility_direct,
            )
            core_evidence = distribution_evidence(
                "material_core", core_contents, CORE_COMMIT, CORE_WHEEL_SHA256,
                core_direct,
            )

            class PinnedDistribution:
                def __init__(self, package_root, package, version, direct, evidence, names):
                    self.root = package_root
                    self.version = version
                    self.files = [Path(f"{package}/{name}") for name in names]
                    self.direct = direct
                    self.evidence = evidence

                def read_text(self, name):
                    return json.dumps(self.direct if name == "direct_url.json" else self.evidence)

                def locate_file(self, name):
                    return self.root / name

            utility = PinnedDistribution(
                utility_root, "credential_patterns", UTILITY_VERSION, utility_direct, utility_evidence,
                ("__init__.py",),
            )
            core = PinnedDistribution(
                core_root, "material_core", CORE_VERSION, core_direct, core_evidence,
                tuple(core_contents),
            )
            (core_package / "contract.py").write_bytes(b"CHANGED_AFTER_VERIFICATION = True\n")
            with patch("control_plane.material_capability.distribution",
                       side_effect=lambda name: core if name == "material-core" else utility):
                require_material_core.cache_clear()
                with self.assertRaises(MaterialCapabilityError):
                    require_material_core()
            self.assertFalse(marker.exists())

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
