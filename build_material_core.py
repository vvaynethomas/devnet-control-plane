"""Explicit authenticated fetch of the pinned producer wheel; no product rebuild."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from release import (MATERIAL_CORE_COMMIT, MATERIAL_CORE_VERSION, verify_material_core_bytes,
                     verify_utility_bytes, UTILITY_VERSION)


def build_release(output_dir: Path) -> dict[str, object]:
    """Retained command compatibility; fetch the published artifact, never clone/build."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = (f"material_core-{MATERIAL_CORE_VERSION}-py3-none-any.whl",
                 f"utility_chest_credential_patterns-{UTILITY_VERSION}-py3-none-any.whl")
    artifacts = []
    with tempfile.TemporaryDirectory(prefix="published-material-core-") as temporary:
        for filename, repo, version, verify in (
            (filenames[0], "vvaynethomas/material-core", MATERIAL_CORE_VERSION, verify_material_core_bytes),
            (filenames[1], "vvaynethomas/utility-chest", UTILITY_VERSION, verify_utility_bytes),
        ):
            subprocess.run(["gh", "release", "download", f"v{version}", "--repo", repo,
                            "--pattern", filename, "--dir", temporary], check=True, timeout=120)
            data = (Path(temporary) / filename).read_bytes()
            artifacts.append(verify(data, filename))
            (output_dir / filename).write_bytes(data)
    manifest = output_dir / "RELEASE_MANIFEST.json"
    manifest.write_text(json.dumps({"name": "material-core", "version": MATERIAL_CORE_VERSION,
                                   "source_commit": MATERIAL_CORE_COMMIT,
                                   "source_sha256": artifacts[0]["source_sha256"],
                                   "artifacts": artifacts}, indent=2), encoding="utf-8")
    return {"wheel": str(output_dir / filenames[0]), "utility_wheel": str(output_dir / filenames[1]),
            "manifest": str(manifest), "artifacts": artifacts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_release(args.output_dir), indent=2))
