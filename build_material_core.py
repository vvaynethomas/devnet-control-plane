"""Build isolated material-core wheel and source archive without network access."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

PROJECT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = PROJECT_DIR / "material_core"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_release(output_dir: Path) -> dict[str, object]:
    metadata = (PACKAGE_DIR / "pyproject.toml").read_text(encoding="utf-8")
    name = re.search(r'(?m)^name\s*=\s*"([^"]+)"$', metadata)
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"$', metadata)
    if not name or not version:
        raise RuntimeError("material-core package metadata is missing name/version")
    name, version = name.group(1), version.group(1)
    normalized_name = name.replace("-", "_")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_files = [PACKAGE_DIR / "__init__.py", PACKAGE_DIR / "contract.py",
                    PACKAGE_DIR / "safety.py", PACKAGE_DIR / "supplied.py"]
    source_files = [*source_files, PACKAGE_DIR / "pyproject.toml", PACKAGE_DIR / "README.md"]
    sdist_path = output_dir / f"{normalized_name}-{version}.tar.gz"
    sdist_root = f"{normalized_name}-{version}"
    with tarfile.open(sdist_path, "w:gz") as archive:
        for source in source_files:
            arcname = f"{sdist_root}/{source.name}"
            info = archive.gettarinfo(str(source), arcname)
            info.mtime = 0
            with source.open("rb") as stream:
                archive.addfile(info, stream)

    with tempfile.TemporaryDirectory(prefix="material-core-wheel-") as temp:
        extracted = Path(temp)
        with tarfile.open(sdist_path, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if (not member.isfile() or len(parts) != 2 or parts[0] != sdist_root
                        or parts[1] in ("", ".", "..")):
                    raise RuntimeError("source archive contains an unexpected path")
                target = extracted / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        source_root = extracted / sdist_root
        wheel_dir = extracted / "wheel"
        wheel_dir.mkdir()
        command = [
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
            "--no-build-isolation", "--wheel-dir", str(wheel_dir), str(source_root),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
        built = list(wheel_dir.glob("*.whl"))
        if len(built) != 1 or built[0].name != f"{normalized_name}-{version}-py3-none-any.whl":
            raise RuntimeError("local core build produced an unexpected wheel identity")
        wheel_path = output_dir / built[0].name
        shutil.copyfile(built[0], wheel_path)

    artifacts = []
    for path in (wheel_path, sdist_path):
        data = path.read_bytes()
        artifacts.append({"filename": path.name, "size_bytes": len(data), "sha256": sha256(data)})
    source_inventory = {source.relative_to(PROJECT_DIR).as_posix(): sha256(source.read_bytes())
                        for source in source_files}
    manifest = {
        "name": name,
        "version": version,
        "source_commit": _git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "source_sha256": source_inventory,
    }
    manifest_path = output_dir / "RELEASE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"wheel": str(wheel_path), "sdist": str(sdist_path), "manifest": str(manifest_path),
            "artifacts": artifacts}


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_DIR), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "dist")
    args = parser.parse_args()
    print(json.dumps(build_release(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
