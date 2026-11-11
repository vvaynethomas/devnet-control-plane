"""Make the network's front door reachable from any folder, IDE or chat on this machine.

    python install_front_door.py            write the launchers and print the MCP settings
    python install_front_door.py --show     print what would be written; change nothing

Writes, under the network data folder (DEVNET_DATA_DIR or ~/.devnet):

  network.json        where each node's checkout is; edit this to repoint, nothing else
  bin/devnet.py       runs this control plane's command line with those paths
  bin/epistemic.py    runs the Epistemic Service's command line
  bin/devnet.cmd, bin/devnet            thin wrappers for cmd/PowerShell and bash

Nothing is installed with pip and no client settings are changed. The launchers read
network.json each time, so moving a checkout (for example from a worktree to main after a
merge) is a one-line edit there. Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEVNET_PY = '''"""Network front door launcher. Paths come from network.json beside this folder."""
import json, os, sys
from pathlib import Path
config = json.loads((Path(__file__).resolve().parent.parent / "network.json").read_text(encoding="utf-8"))
os.environ.setdefault("DEV_NETWORK_ROOT", config["network_root"])
os.environ.setdefault("FACTORY_ROOT", config["incubator_root"])
os.environ.setdefault("DEVNET_REGISTRY_ROOT", config["registry_root"])
os.environ.setdefault("DEVNET_EPISTEMIC_ROOT", config["epistemic_root"])
os.environ.setdefault("DEVNET_DATA_DIR", config["data_dir"])
sys.path.insert(0, config["control_plane_root"])
from control_plane.cli import main
sys.exit(main())
'''

EPISTEMIC_PY = '''"""Epistemic Service launcher. Paths come from network.json beside this folder."""
import json, os, sys
from pathlib import Path
config = json.loads((Path(__file__).resolve().parent.parent / "network.json").read_text(encoding="utf-8"))
os.environ.setdefault("DEVNET_KNOWLEDGE_STORE", str(Path(config["data_dir"]) / "knowledge"))
os.environ.setdefault("DEVNET_EVIDENCE_STORE", str(Path(config["data_dir"]) / "evidence"))
sys.path.insert(0, config["epistemic_root"])
from epistemic.__main__ import main
sys.exit(main())
'''


def plan() -> dict[str, object]:
    sys.path.insert(0, str(HERE))
    from control_plane import DEFAULT_DATA_DIR, DEV_NETWORK_ROOT, FACTORY_ROOT
    from control_plane.front_door import epistemic_root
    from control_plane.network_registry import find_registry_root
    data = Path(DEFAULT_DATA_DIR)
    config = {
        "network_root": str(DEV_NETWORK_ROOT), "control_plane_root": str(HERE), "incubator_root": str(FACTORY_ROOT),
        "registry_root": str(find_registry_root(DEV_NETWORK_ROOT)), "epistemic_root": str(epistemic_root(DEV_NETWORK_ROOT)),
        "data_dir": str(data),
    }
    missing = [name for name, path in config.items() if not Path(path).exists() and name != "data_dir"]
    bin_dir = data / "bin"
    files = {
        data / "network.json": json.dumps(config, indent=2) + "\n",
        bin_dir / "devnet.py": DEVNET_PY, bin_dir / "epistemic.py": EPISTEMIC_PY,
        bin_dir / "devnet.cmd": '@python "%~dp0devnet.py" %*\r\n',
        bin_dir / "devnet": '#!/bin/sh\nexec python "$(dirname "$0")/devnet.py" "$@"\n',
    }
    python = sys.executable.replace("\\", "/")
    mcp = {"mcpServers": {
        "devnet": {"command": python, "args": [str(bin_dir / "devnet.py").replace("\\", "/"), "mcp"]},
        "epistemic": {"command": python, "args": [str(bin_dir / "epistemic.py").replace("\\", "/"), "mcp"]},
    }}
    return {"config": config, "missing": missing, "files": files, "mcp": mcp}


def main(argv: list[str] | None = None) -> int:
    show = "--show" in (argv if argv is not None else sys.argv[1:])
    planned = plan()
    if not show:
        for path, text in planned["files"].items():  # type: ignore[union-attr]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
            if path.name == "devnet" and os.name != "nt":
                path.chmod(0o755)
    print(json.dumps({
        "written" if not show else "would_write": [str(p) for p in planned["files"]],  # type: ignore[union-attr]
        "network": planned["config"], "missing_paths": planned["missing"],
        "mcp_settings": planned["mcp"],
        "next": "Add the two mcp_settings servers to each client (Claude Code: claude mcp add-json --scope user "
                "<name> '<json>'; others: their MCP settings file). The mcp package must be importable by this Python.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
