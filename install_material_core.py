"""Install an offline core wheel and bind its verified manifest to installed bytes."""

import argparse
from importlib.metadata import distribution
import json
from pathlib import Path
import subprocess
import sys
import hashlib

from release import verify_material_core_wheel


def install(wheel: Path) -> None:
    verify_material_core_wheel(wheel)
    manifest = json.loads((wheel.parent / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--force-reinstall", str(wheel)],
                   check=True)
    installed = distribution("material-core")
    hashes = manifest["source_sha256"]
    for name in ("__init__", "contract", "safety", "supplied"):
        relative = f"material_core/{name}.py"
        if hashlib.sha256(Path(installed.locate_file(relative)).read_bytes()).hexdigest() != hashes[relative]:
            raise RuntimeError("Installed core bytes do not match source manifest")
    metadata = next(item for item in installed.files if str(item).endswith(".dist-info/METADATA"))
    evidence = Path(installed.locate_file(metadata)).parent / "dncp_material_provenance.json"
    evidence.write_text(json.dumps({"source_commit": manifest["source_commit"],
                                    "source_sha256": hashes,
                                    "direct_url": json.loads(installed.read_text("direct_url.json"))}),
                        encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    install(parser.parse_args().wheel)
