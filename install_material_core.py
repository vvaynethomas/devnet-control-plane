"""Install two independently digest-pinned wheels and bind installed-byte evidence."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys

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
        workdir = Path(temporary)
        verified = workdir / filename
        verified.write_bytes(data)
        payload = workdir / "install-evidence-input.json"
        payload.write_text(json.dumps({
            "name": name,
            "version": artifact["version"],
            "source_commit": artifact["source_commit"],
            "artifact_sha256": artifact["sha256"],
            "source_sha256": artifact["source_sha256"],
        }), encoding="utf-8")
        environment = _isolated_environment()
        subprocess.run(
            [sys.executable, "-I", "-m", "pip", "install", "--no-index", "--no-deps",
             "--force-reinstall", str(verified)],
            cwd=workdir, env=environment, check=True,
        )
        subprocess.run(
            [sys.executable, "-I", "-c", _VERIFY_INSTALLED_SCRIPT, str(payload)],
            cwd=workdir, env=environment, check=True,
        )


def _isolated_environment():
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "PIP_"))
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


_VERIFY_INSTALLED_SCRIPT = r"""
import hashlib
import json
from importlib.metadata import distribution
from pathlib import Path
import re
import sys

payload_path = Path(sys.argv[1])
payload = json.loads(payload_path.read_text(encoding="utf-8"))
installed = distribution(payload["name"])
def normalize(value):
    return re.sub(r"[-_.]+", "-", value).lower()

if normalize(installed.metadata.get("Name", "")) != normalize(payload["name"]):
    raise RuntimeError("Installed distribution metadata name does not match the requested package")
if installed.version != payload["version"]:
    raise RuntimeError("Installed distribution version does not match verified wheel")
owned = {str(item).replace("\\", "/") for item in (installed.files or ())}
root = Path(installed.locate_file("")).resolve()
for relative, expected in payload["source_sha256"].items():
    if relative not in owned:
        raise RuntimeError("Installed source is not owned by the intended distribution")
    path = Path(installed.locate_file(relative)).resolve()
    path.relative_to(root)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Installed bytes do not match the verified producer wheel")
direct_url_text = installed.read_text("direct_url.json")
if not direct_url_text:
    raise RuntimeError("Installed wheel has no direct URL provenance")
direct_url = json.loads(direct_url_text)
archive_hashes = direct_url.get("archive_info", {}).get("hashes", {})
if archive_hashes.get("sha256") != payload["artifact_sha256"]:
    raise RuntimeError("Installed wheel provenance does not match the verified artifact")
metadata = next(
    item for item in installed.files
    if str(item).replace("\\", "/").endswith(".dist-info/METADATA")
)
evidence = Path(installed.locate_file(metadata)).parent / "dncp_material_provenance.json"
evidence.write_text(json.dumps({
    "source_commit": payload["source_commit"],
    "artifact_sha256": payload["artifact_sha256"],
    "source_sha256": payload["source_sha256"],
    "direct_url": direct_url,
}), encoding="utf-8")
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--utility-wheel", type=Path, required=True)
    args = parser.parse_args()
    install(args.wheel, args.utility_wheel)
