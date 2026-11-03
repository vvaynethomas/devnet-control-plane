"""Optional shared credential-pattern adoption and dependency-free fallback."""

import json
import importlib.abc
import importlib.machinery
import hashlib
import os
from pathlib import Path
import py_compile
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from types import ModuleType

from importlib.metadata import PackageNotFoundError

from control_plane.material_pins import (
    UTILITY_COMMIT,
    UTILITY_SUBDIRECTORY,
    UTILITY_URL,
    UTILITY_VERSION,
    UTILITY_WHEEL_SHA256,
)
from control_plane.safety import (
    CredentialPatternsError,
    SECRET_RE,
    _LOCAL_SECRET_RE,
    _shared_secret_re,
)
from control_plane.verified_package import load_package_from_snapshot, unload_package_snapshot


class TestCredentialPatterns(unittest.TestCase):
    def test_local_redaction_matches_shared_package_policy(self) -> None:
        self.assertEqual(SECRET_RE.pattern, _LOCAL_SECRET_RE.pattern)
        self.assertEqual(SECRET_RE.flags, _LOCAL_SECRET_RE.flags)
        cases = (
            ("ghp_" + "a" * 20, True),
            ("github_pat_" + "b" * 20, True),
            ("sk-" + "c" * 20, True),
            ("AIza" + "d" * 30, True),
            ("Bearer " + "e" * 20, True),
            ("ghp_short", False),
            ("ordinary synthetic text", False),
            ("Bearer " + "f" * 19, False),
        )
        for value, matches in cases:
            with self.subTest(value=value[:12]):
                self.assertEqual(bool(SECRET_RE.search(value)), matches)
                redacted = SECRET_RE.sub("[REDACTED_SECRET]", value)
                self.assertEqual("[REDACTED_SECRET]" in redacted, matches)

    def test_missing_optional_distribution_uses_local_policy(self) -> None:
        with patch(
            "control_plane.safety.distribution",
            side_effect=PackageNotFoundError("utility-chest-credential-patterns"),
        ):
            self.assertIs(_shared_secret_re(), _LOCAL_SECRET_RE)

    def test_wrong_installed_source_fails_explicitly(self) -> None:
        installed = SimpleNamespace(
            version=UTILITY_VERSION,
            read_text=lambda name: json.dumps({
                "url": "https://example.invalid/unrelated.git",
                "vcs_info": {"commit_id": UTILITY_COMMIT},
            }),
        )
        with patch("control_plane.safety.distribution", return_value=installed):
            with self.assertRaisesRegex(CredentialPatternsError, "does not match the pinned"):
                _shared_secret_re()

    def test_mixed_git_and_archive_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "credential_patterns"
            package.mkdir()
            source = (
                "import re\n"
                f"SECRET_RE = re.compile({_LOCAL_SECRET_RE.pattern!r}, flags={_LOCAL_SECRET_RE.flags})\n"
            )
            module = package / "__init__.py"
            module.write_text(source, encoding="utf-8")
            direct = {
                "url": "file:///pinned-wheel.whl",
                "vcs_info": {"vcs": "git", "commit_id": "wrong-commit"},
                "archive_info": {"hashes": {"sha256": "pinned-wheel-digest"}},
            }
            evidence = {
                "source_commit": UTILITY_COMMIT,
                "artifact_sha256": "pinned-wheel-digest",
                "source_sha256": {
                    "credential_patterns/__init__.py": __import__("hashlib").sha256(
                        module.read_bytes()
                    ).hexdigest(),
                },
                "direct_url": direct,
            }

            class AmbiguousDistribution:
                version = UTILITY_VERSION
                files = [Path("credential_patterns/__init__.py")]

                @staticmethod
                def read_text(name: str) -> str:
                    return json.dumps(direct if name == "direct_url.json" else evidence)

                @staticmethod
                def locate_file(name: str) -> Path:
                    return root / name

            with patch("control_plane.safety.distribution", return_value=AmbiguousDistribution()):
                with self.assertRaisesRegex(CredentialPatternsError, "does not match the pinned"):
                    _shared_secret_re()

    def test_digest_verified_archive_provenance_loads_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "credential_patterns"
            package.mkdir()
            source = (
                "import re\n"
                f"SECRET_RE = re.compile({_LOCAL_SECRET_RE.pattern!r}, flags={_LOCAL_SECRET_RE.flags})\n"
            ).encode()
            (package / "__init__.py").write_bytes(source)
            direct = {
                "url": "file:///verified-utility.whl",
                "archive_info": {"hashes": {"sha256": UTILITY_WHEEL_SHA256}},
            }
            evidence = {
                "source_commit": UTILITY_COMMIT,
                "artifact_sha256": UTILITY_WHEEL_SHA256,
                "source_sha256": {
                    "credential_patterns/__init__.py": hashlib.sha256(source).hexdigest(),
                },
                "direct_url": direct,
            }

            class PinnedDistribution:
                version = UTILITY_VERSION
                files = [Path("credential_patterns/__init__.py")]

                @staticmethod
                def read_text(name: str) -> str:
                    return json.dumps(direct if name == "direct_url.json" else evidence)

                @staticmethod
                def locate_file(name: str) -> Path:
                    return root / name

            with patch("control_plane.safety.distribution", return_value=PinnedDistribution()):
                loaded = _shared_secret_re()
            self.assertEqual(loaded.pattern, _LOCAL_SECRET_RE.pattern)
            self.assertEqual(loaded.flags, _LOCAL_SECRET_RE.flags)

    def test_pinned_distribution_is_loaded_outside_import_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "credential_patterns"
            package.mkdir()
            source = (
                "import re\n"
                f"SECRET_RE = re.compile({_LOCAL_SECRET_RE.pattern!r}, flags={_LOCAL_SECRET_RE.flags})\n"
            )
            (package / "__init__.py").write_text(source, encoding="utf-8")
            direct = {
                "url": f"{UTILITY_URL}.git",
                "vcs_info": {"vcs": "git", "commit_id": UTILITY_COMMIT},
                "subdirectory": UTILITY_SUBDIRECTORY,
            }

            class PinnedDistribution:
                version = UTILITY_VERSION
                files = [Path("credential_patterns/__init__.py")]

                @staticmethod
                def read_text(name: str) -> str:
                    return json.dumps(direct) if name == "direct_url.json" else None

                @staticmethod
                def locate_file(name: str) -> Path:
                    return root / name

            shadow = ModuleType("credential_patterns")
            shadow.SECRET_RE = re.compile("shadow")
            with patch("control_plane.safety.distribution", return_value=PinnedDistribution()), \
                    patch.dict(sys.modules, {"credential_patterns": shadow}):
                loaded = _shared_secret_re()
                loaded_module = sys.modules["_dncp_pinned_credential_patterns"]
                self.assertIs(sys.modules["credential_patterns"], shadow)

            self.assertEqual(loaded.pattern, _LOCAL_SECRET_RE.pattern)
            self.assertEqual(loaded.flags, _LOCAL_SECRET_RE.flags)
            self.assertEqual(
                Path(loaded_module.__file__).resolve(),
                (package / "__init__.py").resolve(),
            )
            (package / "__init__.py").write_text(
                "import re\nSECRET_RE = re.compile('no longer the reviewed policy')\n",
                encoding="utf-8",
            )
            with patch("control_plane.safety.distribution", return_value=PinnedDistribution()):
                with self.assertRaisesRegex(CredentialPatternsError, "behavior differs"):
                    _shared_secret_re()

    def test_transitive_utility_source_bypasses_cached_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "credential_patterns"
            package.mkdir()
            (package / "__init__.py").write_text("from .rules import SECRET_RE\n", encoding="utf-8")
            rules = package / "rules.py"
            source = (
                "import re\n"
                f"SECRET_RE = re.compile({_LOCAL_SECRET_RE.pattern!r}, flags={_LOCAL_SECRET_RE.flags})\n"
            )
            poison = "import re\nSECRET_RE = re.compile('cached-bytecode-shadow')\n".ljust(len(source))
            rules.write_text(poison, encoding="utf-8")
            cached = Path(py_compile.compile(str(rules), doraise=True))
            timestamp = rules.stat().st_mtime
            rules.write_text(source, encoding="utf-8")
            os.utime(rules, (timestamp, timestamp))
            self.assertTrue(cached.is_file())
            direct = {
                "url": f"{UTILITY_URL}.git",
                "vcs_info": {"vcs": "git", "commit_id": UTILITY_COMMIT},
                "subdirectory": UTILITY_SUBDIRECTORY,
            }

            class PinnedDistribution:
                version = UTILITY_VERSION
                files = [Path("credential_patterns/__init__.py"), Path("credential_patterns/rules.py")]

                @staticmethod
                def read_text(name: str) -> str:
                    return json.dumps(direct) if name == "direct_url.json" else "{}"

                @staticmethod
                def locate_file(name: str) -> Path:
                    return root / name

            with patch("control_plane.safety.distribution", return_value=PinnedDistribution()):
                loaded = _shared_secret_re()
            self.assertEqual(loaded.pattern, _LOCAL_SECRET_RE.pattern)
            self.assertEqual(loaded.flags, _LOCAL_SECRET_RE.flags)

    def test_missing_snapshot_module_does_not_fall_through_to_other_finder(self) -> None:
        marker = []
        namespace = "_dncp_test_missing_snapshot"

        class FallbackLoader(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                marker.append("executed")

        class FallbackFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == namespace + ".missing":
                    return importlib.machinery.ModuleSpec(fullname, FallbackLoader())
                return None

        fallback = FallbackFinder()
        sys.meta_path.append(fallback)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package = root / "__init__.py"
                package.write_text("from .missing import value\n", encoding="utf-8")
                with self.assertRaisesRegex(ModuleNotFoundError, namespace + r"\.missing"):
                    load_package_from_snapshot(
                        "test-package",
                        namespace,
                        {"__init__.py": (package, package.read_bytes())},
                    )
            self.assertEqual(marker, [])
        finally:
            if fallback in sys.meta_path:
                sys.meta_path.remove(fallback)
            unload_package_snapshot(namespace)


if __name__ == "__main__":
    unittest.main()
