"""Deterministic System Node Release Builder (ALM-006 / DEC-0015 / ART-0008).

Builds PEP 427 pure-Python wheels, source archives, and SHA-256 manifests using
the standard library, against an explicitly supplied local material-core wheel.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

PROJECT_DIR = Path(__file__).resolve().parent
PACKAGE_NAME = "devnet-control-plane"
DISTRIBUTION_NAME = "devnet_control_plane"
VERSION = "0.1.0"
MATERIAL_CORE_NAME = "material-core"
MATERIAL_CORE_VERSION = "0.1.0"


def compute_sha256(data: bytes) -> str:
    """Compute hex SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def compute_urlsafe_b64_sha256(data: bytes) -> str:
    """Compute base64 urlsafe SHA-256 for PEP 376 / 427 RECORD entry."""
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def get_git_commit(repo_dir: Path) -> str:
    """Retrieve current git commit hash, falling back to 'unknown'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unversioned"


def collect_source_files(pkg_dir: Path) -> list[tuple[str, bytes]]:
    """Collect source files from the system-node package."""
    files = []
    for p in sorted(pkg_dir.rglob("*")):
        if p.is_file() and not p.name.endswith((".pyc", ".pyo")) and "__pycache__" not in p.parts:
            rel = p.relative_to(pkg_dir.parent).as_posix()
            files.append((rel, p.read_bytes()))
    registry = pkg_dir.parent / "registry" / "interaction_frames.json"
    files.append(("control_plane/registry/interaction_frames.json", registry.read_bytes()))
    return files


def verify_material_core_wheel(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"required local {MATERIAL_CORE_NAME} wheel not found: {path}")
    expected_filename = "material_core-0.1.0-py3-none-any.whl"
    if path.name != expected_filename:
        raise ValueError(f"expected pinned core wheel filename {expected_filename}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("material-core wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
        if not all(name in names for name in (
            "material_core/__init__.py", "material_core/contract.py", "material_core/supplied.py"
        )):
            raise ValueError("material-core wheel is missing required package modules")
    if metadata["Name"] != MATERIAL_CORE_NAME or metadata["Version"] != MATERIAL_CORE_VERSION:
        raise ValueError(
            f"DNCP requires {MATERIAL_CORE_NAME}=={MATERIAL_CORE_VERSION}; "
            f"got {metadata['Name']}=={metadata['Version']}"
        )
    data = path.read_bytes()
    return {"filename": path.name, "version": metadata["Version"], "sha256": compute_sha256(data),
            "size_bytes": len(data)}


def build_wheel(dist_dir: Path, source_files: list[tuple[str, bytes]]) -> Path:
    """Construct PEP 427 compliant pure-Python wheel."""
    dist_info = f"{DISTRIBUTION_NAME}-{VERSION}.dist-info"
    wheel_filename = f"{DISTRIBUTION_NAME}-{VERSION}-py3-none-any.whl"
    wheel_path = dist_dir / wheel_filename

    metadata_content = f"""Metadata-Version: 2.1
Name: {PACKAGE_NAME}
Version: {VERSION}
Summary: Autonomous Development Network Control Plane and Interaction Frame Lab
Author: Development Network Operator
License: MIT
Requires-Python: >=3.10
Requires-Dist: material-core=={MATERIAL_CORE_VERSION}
Provides-Extra: mcp
Requires-Dist: mcp>=1.30,<2; extra == "mcp"
Provides-Extra: llm
Requires-Dist: openai>=1.0.0; extra == "llm"
Description-Content-Type: text/markdown

# {PACKAGE_NAME}

Autonomous Development Network Control Plane, Conversation Fabric, and Interaction Frame Lab.
Delivered as a standalone system node under DEC-0015 and ART-0008.
""".encode("utf-8")

    wheel_meta = b"""Wheel-Version: 1.0
Generator: devnet-release-builder (0.1.0)
Root-Is-Purelib: true
Tag: py3-none-any
"""

    entry_points = b"""[console_scripts]
devnet = control_plane.cli:main
devnet-control-plane = control_plane.cli:main
"""

    record_entries = []
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write package source files
        for arcname, data in source_files:
            zf.writestr(arcname, data)
            b64_hash = compute_urlsafe_b64_sha256(data)
            record_entries.append(f"{arcname},sha256={b64_hash},{len(data)}")

        # Write dist-info files
        for name, data in [
            (f"{dist_info}/METADATA", metadata_content),
            (f"{dist_info}/WHEEL", wheel_meta),
            (f"{dist_info}/entry_points.txt", entry_points),
        ]:
            zf.writestr(name, data)
            b64_hash = compute_urlsafe_b64_sha256(data)
            record_entries.append(f"{name},sha256={b64_hash},{len(data)}")

        # Write RECORD
        record_entries.append(f"{dist_info}/RECORD,,")
        zf.writestr(f"{dist_info}/RECORD", "\n".join(record_entries) + "\n")

    return wheel_path


def build_sdist(dist_dir: Path, source_files: list[tuple[str, bytes]]) -> Path:
    """Construct source distribution tarball (*.tar.gz)."""
    sdist_name = f"{DISTRIBUTION_NAME}-{VERSION}"
    sdist_filename = f"{sdist_name}.tar.gz"
    sdist_path = dist_dir / sdist_filename

    readme_bytes = (PROJECT_DIR / "README.md").read_bytes() if (PROJECT_DIR / "README.md").exists() else b"# Readme"
    pyproject_bytes = (PROJECT_DIR / "pyproject.toml").read_bytes() if (PROJECT_DIR / "pyproject.toml").exists() else b""

    with tarfile.open(sdist_path, "w:gz") as tf:
        # Add pyproject.toml and README
        for name, data in [("pyproject.toml", pyproject_bytes), ("README.md", readme_bytes)]:
            if data:
                ti = tarfile.TarInfo(f"{sdist_name}/{name}")
                ti.size = len(data)
                ti.mtime = int(datetime.now(timezone.utc).timestamp())
                tf.addfile(ti, io_bytes(data))

        # Add package sources
        for arcname, data in source_files:
            ti = tarfile.TarInfo(f"{sdist_name}/{arcname}")
            ti.size = len(data)
            ti.mtime = int(datetime.now(timezone.utc).timestamp())
            tf.addfile(ti, io_bytes(data))
        registry = PROJECT_DIR / "registry" / "interaction_frames.json"
        ti = tarfile.TarInfo(f"{sdist_name}/registry/interaction_frames.json")
        ti.size = registry.stat().st_size
        tf.addfile(ti, io_bytes(registry.read_bytes()))

    return sdist_path


def io_bytes(data: bytes):
    import io
    return io.BytesIO(data)


def build_release(output_dir: Path, material_core_wheel: Path) -> dict[str, object]:
    """Build DNCP against an explicit, verified local material-core wheel."""
    core_artifact = verify_material_core_wheel(material_core_wheel)
    dist_dir = output_dir
    dist_dir.mkdir(parents=True, exist_ok=True)

    pkg_dir = PROJECT_DIR / "control_plane"
    sources = collect_source_files(pkg_dir)

    source_digests = {}
    for arcname, data in sources:
        source_digests[arcname] = compute_sha256(data)

    wheel_path = build_wheel(dist_dir, sources)
    sdist_path = build_sdist(dist_dir, sources)

    wheel_bytes = wheel_path.read_bytes()
    sdist_bytes = sdist_path.read_bytes()

    artifacts = [
        {
            "filename": wheel_path.name,
            "format": "wheel",
            "size_bytes": len(wheel_bytes),
            "sha256": compute_sha256(wheel_bytes),
            "content_type": "application/x-wheel+zip",
        },
        {
            "filename": sdist_path.name,
            "format": "sdist",
            "size_bytes": len(sdist_bytes),
            "sha256": compute_sha256(sdist_bytes),
            "content_type": "application/gzip",
        },
    ]

    manifest = {
        "package_name": PACKAGE_NAME,
        "version": VERSION,
        "release_timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(PROJECT_DIR.parent.parent),
        "protocol": "DEC-0015",
        "task_id": "ALM-006",
        "deliverable_id": "ART-0008",
        "runtime_requirements": {
            "python": ">=3.10",
            "dependencies": [f"{MATERIAL_CORE_NAME}=={MATERIAL_CORE_VERSION}"],
            "optional_extras": ["openai>=1.0.0", "mcp>=1.30,<2"],
        },
        "material_core_artifact": core_artifact,
        "artifacts": artifacts,
        "source_inventory": {
            "file_count": len(sources),
            "digests": source_digests,
        },
        "consumer_pin": {
            "pip_command": f"pip install --no-index --find-links <core-wheelhouse> dist/{wheel_path.name}",
            "requirements_entry": f"{PACKAGE_NAME}=={VERSION}",
            "sha256_pin": f"{PACKAGE_NAME}=={VERSION} --hash=sha256:{compute_sha256(wheel_bytes)}",
        },
    }

    manifest_path = dist_dir / "RELEASE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "manifest_path": str(manifest_path),
        "artifacts": artifacts,
        "wheel": str(wheel_path),
        "sdist": str(sdist_path),
        "material_core": core_artifact,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--material-core-wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "dist")
    args = parser.parse_args()
    out = build_release(args.output_dir, args.material_core_wheel)
    print(json.dumps(out, indent=2))
