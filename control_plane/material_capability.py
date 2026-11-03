"""Load optional processing only from a provenance-checked distribution."""

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, distribution
import importlib.util
import hashlib
import json
from pathlib import Path
import sys

CORE_VERSION = "0.1.0"
CORE_COMMIT = "108fe9f309005ac7593fd640fce54bc196262198"
CORE_URL = "https://github.com/vvaynethomas/material-core"
FORMATS = ("text", "markdown", "csv", "html", "json", "python", "zip")
INSTALL_GUIDANCE = (
    'Install with authenticated private repository access: '
    'pip install "devnet-control-plane[material]"; for offline wheels use '
    'install_material_core.py with the verified source manifest. '
    f"Required material-core=={CORE_VERSION} at commit {CORE_COMMIT}."
)


class MaterialCapabilityError(ValueError):
    status = 503


@lru_cache(maxsize=1)
def require_material_core():
    try:
        installed = distribution("material-core")
    except PackageNotFoundError:
        raise MaterialCapabilityError("Material capability is not installed. " + INSTALL_GUIDANCE) from None
    try:
        direct = json.loads(installed.read_text("direct_url.json") or "{}")
        vcs = direct.get("vcs_info", {})
        verified = (direct.get("url", "").removesuffix(".git") == CORE_URL
                    and vcs.get("commit_id") == CORE_COMMIT)
        if not verified:
            evidence = json.loads(installed.read_text("dncp_material_provenance.json") or "{}")
            verified = (evidence.get("source_commit") == CORE_COMMIT
                        and evidence.get("direct_url") == direct)
            hashes = evidence.get("source_sha256", {})
            required = {f"material_core/{name}.py" for name in ("__init__", "contract", "safety", "supplied")}
            if not required <= hashes.keys():
                verified = False
            for name in required:
                if verified and hashlib.sha256(Path(installed.locate_file(name)).read_bytes()).hexdigest() != hashes[name]:
                    verified = False
        if installed.version != CORE_VERSION or not verified:
            raise ValueError("unverified version/source")
        files = {str(item).replace("\\", "/") for item in (installed.files or ())}
        required = {f"material_core/{name}.py" for name in ("__init__", "contract", "safety", "supplied")}
        root = Path(installed.locate_file("")).resolve()
        for name in required:
            path = Path(installed.locate_file(name)).resolve()
            path.relative_to(root)
            if name not in files or not path.is_file():
                raise ValueError("missing owned processor file")
        path = Path(installed.locate_file("material_core/__init__.py")).resolve()
        namespace = "_dncp_verified_material_core"
        for name in tuple(sys.modules):
            if name == namespace or name.startswith(namespace + "."):
                del sys.modules[name]
        spec = importlib.util.spec_from_file_location(namespace, path,
                                                       submodule_search_locations=[str(path.parent)])
        if spec is None or spec.loader is None:
            raise ImportError("cannot load verified processor")
        core = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = core
        spec.loader.exec_module(core)
        if core.__version__ != CORE_VERSION:
            raise ValueError("module version mismatch")
        return core
    except (ValueError, OSError, ImportError, SyntaxError, AttributeError, TypeError) as exc:
        for name in tuple(sys.modules):
            if name == "_dncp_verified_material_core" or name.startswith("_dncp_verified_material_core."):
                del sys.modules[name]
        raise MaterialCapabilityError(
            f"DNCP requires material-core=={CORE_VERSION} with verified source provenance. " + INSTALL_GUIDANCE
        ) from exc
