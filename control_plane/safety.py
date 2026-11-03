"""Credential filtering with an optional, provenance-checked shared primitive."""

from importlib.metadata import PackageNotFoundError, distribution
import hashlib
import json
import re
from pathlib import Path

from .verified_package import (
    SNAPSHOT_LOAD_LOCK,
    capture_distribution_sources,
    load_package_from_snapshot,
    unload_package_snapshot,
)
from .material_pins import (
    UTILITY_COMMIT,
    UTILITY_SUBDIRECTORY,
    UTILITY_URL,
    UTILITY_VERSION,
    UTILITY_WHEEL_SHA256,
)


_LOCAL_SECRET_RE = re.compile(
    r"(?i)(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|Bearer\s+[A-Za-z0-9._-]{20,})"
)


class CredentialPatternsError(RuntimeError):
    """The optional shared pattern package is installed but does not match its pin."""


def _verified_pin_mode(installed) -> str | None:
    if installed.version != UTILITY_VERSION:
        return None
    try:
        direct = json.loads(installed.read_text("direct_url.json") or "{}")
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(direct, dict):
        return None

    if "vcs_info" in direct:
        vcs_info = direct["vcs_info"]
        if ("archive_info" not in direct and isinstance(direct.get("url"), str)
                and direct["url"].removesuffix(".git") == UTILITY_URL
                and isinstance(vcs_info, dict)
                and vcs_info.get("commit_id") == UTILITY_COMMIT
                and direct.get("subdirectory") == UTILITY_SUBDIRECTORY):
            return "vcs"
        return None
    if "archive_info" not in direct:
        return None

    try:
        evidence = json.loads(installed.read_text("dncp_material_provenance.json") or "{}")
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(evidence, dict):
        return None
    relative = "credential_patterns/__init__.py"
    hashes = evidence.get("source_sha256")
    archive_info = direct.get("archive_info")
    artifact_hashes = archive_info.get("hashes") if isinstance(archive_info, dict) else None
    if (
        evidence.get("source_commit") != UTILITY_COMMIT
        or evidence.get("artifact_sha256") != UTILITY_WHEEL_SHA256
        or evidence.get("direct_url") != direct
        or not isinstance(artifact_hashes, dict)
        or artifact_hashes.get("sha256") != UTILITY_WHEEL_SHA256
        or not isinstance(hashes, dict)
        or relative not in hashes
    ):
        return None
    try:
        installed_file = Path(installed.locate_file(relative))
        if hashlib.sha256(installed_file.read_bytes()).hexdigest() == hashes[relative]:
            return "wheel"
        return None
    except (OSError, TypeError):
        return None


def _shared_secret_re() -> re.Pattern[str]:
    try:
        installed = distribution("utility-chest-credential-patterns")
    except PackageNotFoundError:
        return _LOCAL_SECRET_RE
    with SNAPSHOT_LOAD_LOCK:
        mode = _verified_pin_mode(installed)
        if mode is None:
            raise CredentialPatternsError(
                "Installed utility-chest-credential-patterns does not match the pinned "
                f"v{UTILITY_VERSION} source commit {UTILITY_COMMIT}."
            )
        return _load_shared_secret_re(installed, mode)


def _load_shared_secret_re(installed, mode: str) -> re.Pattern[str]:
    try:
        evidence = json.loads(installed.read_text("dncp_material_provenance.json") or "{}")
        expected_hashes = evidence.get("source_sha256") if mode == "wheel" else None
        sources = capture_distribution_sources(
            installed, "credential_patterns", {"credential_patterns/__init__.py"}, expected_hashes,
        )
        module = load_package_from_snapshot(
            "credential_patterns", "_dncp_pinned_credential_patterns", sources,
        )
    except (ImportError, OSError, SyntaxError, ValueError, TypeError, KeyError) as exc:
        raise CredentialPatternsError(
            "Pinned credential-patterns module cannot be loaded from verified source."
        ) from exc
    pattern = getattr(module, "SECRET_RE", None)
    if (
        not isinstance(pattern, re.Pattern)
        or pattern.pattern != _LOCAL_SECRET_RE.pattern
        or pattern.flags != _LOCAL_SECRET_RE.flags
    ):
        unload_package_snapshot("_dncp_pinned_credential_patterns")
        raise CredentialPatternsError(
            "Pinned credential-patterns behavior differs from DNCP's reviewed policy."
        )
    return pattern


SECRET_RE = _shared_secret_re()
