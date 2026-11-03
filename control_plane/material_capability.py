"""Load optional material processing from provenance-checked distributions."""

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, distribution
import importlib.util
import hashlib
import json
from pathlib import Path
import sys

from .material_pins import (
    CORE_VERSION, CORE_COMMIT, CORE_URL, CORE_WHEEL_SHA256,
    UTILITY_VERSION, UTILITY_COMMIT, UTILITY_URL, UTILITY_WHEEL_SHA256, UTILITY_SUBDIRECTORY,
)

FORMATS = ("text", "markdown", "csv", "html", "json", "python", "zip")
INSTALL_GUIDANCE = (
    'Install with authenticated private repository access: '
    'pip install "devnet-control-plane[material]"; for offline use '
    'install_material_core.py with both digest-pinned producer wheels. '
    f"Required material-core=={CORE_VERSION} at commit {CORE_COMMIT}, "
    f"and Utility Chest credential-patterns=={UTILITY_VERSION} at {UTILITY_COMMIT}."
)


class MaterialCapabilityError(ValueError):
    status = 503


def _load_owned(name, version, commit, url, digest, package, modules, subdirectory=None):
    installed = distribution(name)
    direct = json.loads(installed.read_text("direct_url.json") or "{}")
    verified = (direct.get("url", "").removesuffix(".git") == url
                and direct.get("vcs_info", {}).get("commit_id") == commit
                and direct.get("subdirectory") == subdirectory)
    required = {f"{package}/{module}.py" for module in modules}
    if not verified:
        evidence = json.loads(installed.read_text("dncp_material_provenance.json") or "{}")
        verified = (evidence.get("source_commit") == commit
                    and evidence.get("direct_url") == direct
                    and evidence.get("artifact_sha256") == digest
                    and direct.get("archive_info", {}).get("hashes", {}).get("sha256") == digest)
        hashes = evidence.get("source_sha256", {})
        verified = verified and required <= hashes.keys()
        for module in required:
            if verified and hashlib.sha256(Path(installed.locate_file(module)).read_bytes()).hexdigest() != hashes[module]:
                verified = False
    if installed.version != version or not verified:
        raise ValueError(f"{name} has unverified version/source")
    owned = {str(item).replace("\\", "/") for item in (installed.files or ())}
    root = Path(installed.locate_file("")).resolve()
    for module in required:
        path = Path(installed.locate_file(module)).resolve()
        path.relative_to(root)
        if module not in owned or not path.is_file():
            raise ValueError(f"{name} is missing an owned file")
    namespace = f"_dncp_verified_{package}"
    for module in tuple(sys.modules):
        if module == namespace or module.startswith(namespace + "."):
            del sys.modules[module]
    path = Path(installed.locate_file(f"{package}/__init__.py")).resolve()
    spec = importlib.util.spec_from_file_location(namespace, path,
                                                   submodule_search_locations=[str(path.parent)])
    if spec is None or spec.loader is None:
        raise ImportError("cannot load verified processor dependency")
    module = importlib.util.module_from_spec(spec)
    sys.modules[namespace] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def require_material_core():
    try:
        # Resolve producer provenance before executing either package.
        distribution("material-core")
        utility = _load_owned("utility-chest-credential-patterns", UTILITY_VERSION, UTILITY_COMMIT,
                              UTILITY_URL, UTILITY_WHEEL_SHA256, "credential_patterns", ("__init__",),
                              UTILITY_SUBDIRECTORY)
        previous = sys.modules.get("credential_patterns")
        sys.modules["credential_patterns"] = utility
        try:
            core = _load_owned("material-core", CORE_VERSION, CORE_COMMIT, CORE_URL, CORE_WHEEL_SHA256,
                               "material_core", ("__init__", "contract", "safety", "supplied"))
        finally:
            if previous is None:
                sys.modules.pop("credential_patterns", None)
            else:
                sys.modules["credential_patterns"] = previous
        if core.__version__ != CORE_VERSION:
            raise ValueError("module version mismatch")
        return core
    except PackageNotFoundError as exc:
        raise MaterialCapabilityError(
            "Material capability is not installed or its private utility dependency is missing. " + INSTALL_GUIDANCE
        ) from exc
    except (ValueError, OSError, ImportError, SyntaxError, AttributeError, TypeError) as exc:
        for module in tuple(sys.modules):
            if module.startswith("_dncp_verified_material_core") or module.startswith("_dncp_verified_credential_patterns"):
                del sys.modules[module]
        raise MaterialCapabilityError(
            f"DNCP requires material-core=={CORE_VERSION} with verified source provenance. " + INSTALL_GUIDANCE
        ) from exc
