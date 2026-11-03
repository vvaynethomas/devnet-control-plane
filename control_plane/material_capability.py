"""Load optional material processing from provenance-checked distributions."""

from importlib.metadata import PackageNotFoundError, distribution
import json
import sys

from .verified_package import (
    SNAPSHOT_LOAD_LOCK,
    capture_distribution_sources,
    load_package_from_snapshot,
    unload_package_snapshot,
)
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


_CACHE_EMPTY = object()
_material_core = _CACHE_EMPTY


def _prepare_owned(name, version, commit, url, digest, package, modules, subdirectory=None):
    installed = distribution(name)
    direct = json.loads(installed.read_text("direct_url.json") or "{}")
    if not isinstance(direct, dict):
        raise ValueError(f"{name} has malformed direct URL provenance")

    vcs_info = direct.get("vcs_info")
    archive_info = direct.get("archive_info")
    if "vcs_info" in direct:
        if not isinstance(vcs_info, dict) or "archive_info" in direct:
            raise ValueError(f"{name} has ambiguous source provenance")
        verified = (
            direct.get("url", "").removesuffix(".git") == url
            and vcs_info.get("commit_id") == commit
            and direct.get("subdirectory") == subdirectory
        )
        hashes = None
    elif "archive_info" in direct:
        evidence = json.loads(installed.read_text("dncp_material_provenance.json") or "{}")
        archive_hashes = archive_info.get("hashes") if isinstance(archive_info, dict) else None
        hashes = evidence.get("source_sha256") if isinstance(evidence, dict) else None
        verified = (
            isinstance(evidence, dict)
            and evidence.get("source_commit") == commit
            and evidence.get("direct_url") == direct
            and evidence.get("artifact_sha256") == digest
            and isinstance(archive_hashes, dict)
            and archive_hashes.get("sha256") == digest
            and isinstance(hashes, dict)
        )
    else:
        raise ValueError(f"{name} has no supported source provenance")

    required = {f"{package}/{module.replace('.', '/')}.py" for module in modules}
    if "__init__" in modules:
        required.add(f"{package}/__init__.py")
    if installed.version != version or not verified:
        raise ValueError(f"{name} has unverified version/source")
    return capture_distribution_sources(installed, package, required, hashes)


def require_material_core():
    global _material_core
    with SNAPSHOT_LOAD_LOCK:
        if _material_core is not _CACHE_EMPTY:
            return _material_core
        try:
            # Validate both distributions and capture their complete source snapshots before execution.
            utility_sources = _prepare_owned(
                "utility-chest-credential-patterns", UTILITY_VERSION, UTILITY_COMMIT,
                UTILITY_URL, UTILITY_WHEEL_SHA256, "credential_patterns", ("__init__",),
                UTILITY_SUBDIRECTORY,
            )
            core_sources = _prepare_owned(
                "material-core", CORE_VERSION, CORE_COMMIT, CORE_URL, CORE_WHEEL_SHA256,
                "material_core", ("__init__", "contract", "safety", "supplied"),
            )
            utility = load_package_from_snapshot(
                "credential_patterns", "_dncp_verified_credential_patterns", utility_sources,
            )
            previous = sys.modules.get("credential_patterns")
            sys.modules["credential_patterns"] = utility
            try:
                core = load_package_from_snapshot(
                    "material_core", "_dncp_verified_material_core", core_sources,
                )
            finally:
                if previous is None:
                    sys.modules.pop("credential_patterns", None)
                else:
                    sys.modules["credential_patterns"] = previous
            if core.__version__ != CORE_VERSION:
                raise ValueError("module version mismatch")
            _material_core = core
            return core
        except PackageNotFoundError as exc:
            raise MaterialCapabilityError(
                "Material capability is not installed or its private utility dependency is missing. "
                + INSTALL_GUIDANCE
            ) from exc
        except (ValueError, OSError, ImportError, SyntaxError, AttributeError, TypeError, KeyError) as exc:
            unload_package_snapshot("_dncp_verified_material_core")
            unload_package_snapshot("_dncp_verified_credential_patterns")
            raise MaterialCapabilityError(
                f"DNCP requires material-core=={CORE_VERSION} with verified source provenance. "
                + INSTALL_GUIDANCE
            ) from exc


def clear_material_core_cache():
    global _material_core
    with SNAPSHOT_LOAD_LOCK:
        _material_core = _CACHE_EMPTY
        unload_package_snapshot("_dncp_verified_material_core")
        unload_package_snapshot("_dncp_verified_credential_patterns")
