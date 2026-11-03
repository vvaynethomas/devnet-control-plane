"""Explicitly fetch and build DNCP's immutable external core dependency.

This command needs authenticated GitHub access and locally installed build
tools. It never falls back to in-tree sources or a mutable branch/tag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from release import MATERIAL_CORE_COMMIT

SOURCE_URL = "https://github.com/vvaynethomas/material-core.git"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_release(output_dir: Path) -> dict[str, object]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="external-material-core-") as temporary:
        source = Path(temporary) / "source"
        subprocess.run(["git", "clone", "--quiet", SOURCE_URL, str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--quiet", MATERIAL_CORE_COMMIT],
                       check=True)
        actual = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                check=True, capture_output=True, text=True).stdout.strip()
        if actual != MATERIAL_CORE_COMMIT:
            raise RuntimeError("external core checkout did not match the immutable pin")
        files = subprocess.run(["git", "-C", str(source), "ls-files"],
                               check=True, capture_output=True, text=True).stdout.splitlines()
        inventory = {name: sha256((source / name).read_bytes()) for name in files}
        sdist = output_dir / "material_core-0.1.0.tar.gz"
        with tarfile.open(sdist, "w:gz") as archive:
            for name in files:
                archive.add(source / name, arcname=f"material_core-0.1.0/{name}", recursive=False)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                        "--no-build-isolation", "--wheel-dir", str(output_dir), str(source)],
                       check=True, timeout=120)
    wheel = output_dir / "material_core-0.1.0-py3-none-any.whl"
    artifacts = [{"filename": path.name, "size_bytes": path.stat().st_size,
                  "sha256": sha256(path.read_bytes())} for path in (wheel, sdist)]
    manifest = output_dir / "RELEASE_MANIFEST.json"
    manifest.write_text(json.dumps({"name": "material-core", "version": "0.1.0",
                                   "source_url": SOURCE_URL,
                                   "source_commit": MATERIAL_CORE_COMMIT,
                                   "source_sha256": inventory,
                                   "artifacts": artifacts}, indent=2), encoding="utf-8")
    return {"wheel": str(wheel), "sdist": str(sdist), "manifest": str(manifest),
            "artifacts": artifacts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_release(args.output_dir), indent=2))
