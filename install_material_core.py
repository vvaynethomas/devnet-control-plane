"""Install two independently digest-pinned wheels and bind installed-byte evidence."""

import argparse
from importlib.metadata import distribution
import json
from pathlib import Path
import subprocess
import tempfile
import sys
import hashlib

from release import verify_material_core_bytes, verify_utility_bytes


def install(wheel: Path, utility_wheel: Path) -> None:
    data = wheel.read_bytes()
    artifact = verify_material_core_bytes(data, wheel.name)
    utility_data = utility_wheel.read_bytes()
    utility_artifact = verify_utility_bytes(utility_data, utility_wheel.name)
    _install_verified(utility_data, utility_wheel.name, utility_artifact, "utility-chest-credential-patterns")
    _install_verified(data, wheel.name, artifact, "material-core")


def _install_verified(data, filename, artifact, name):
    with tempfile.TemporaryDirectory(prefix="verified-core-install-") as temporary:
        verified = Path(temporary) / filename
        verified.write_bytes(data)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                        "--force-reinstall", str(verified)],
                       check=True)
    installed = distribution(name)
    hashes = artifact["source_sha256"]
    for relative in hashes:
        if hashlib.sha256(Path(installed.locate_file(relative)).read_bytes()).hexdigest() != hashes[relative]:
            raise RuntimeError("Installed bytes do not match the verified producer wheel")
    metadata = next(item for item in installed.files if str(item).endswith(".dist-info/METADATA"))
    evidence = Path(installed.locate_file(metadata)).parent / "dncp_material_provenance.json"
    evidence.write_text(json.dumps({"source_commit": artifact["source_commit"],
                                    "artifact_sha256": artifact["sha256"],
                                    "source_sha256": hashes,
                                    "direct_url": json.loads(installed.read_text("direct_url.json"))}),
                        encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--utility-wheel", type=Path, required=True)
    args = parser.parse_args()
    install(args.wheel, args.utility_wheel)
