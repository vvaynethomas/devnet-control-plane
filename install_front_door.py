"""Make the network's front door reachable from any folder, IDE or chat on this machine.

    python install_front_door.py            copy the code to ~/.devnet/app, write the launchers, print MCP settings
    python install_front_door.py --live     point the launchers at the checkouts instead of copies (development)
    python install_front_door.py --show     print what would be written; change nothing
    python install_front_door.py --check    say whether the installation works and whether its copies are stale

Writes, under the network data folder (DEVNET_DATA_DIR or ~/.devnet):

  app/                a copy of this control plane and of the Epistemic Service, so removing a worktree
                      or switching a branch cannot break the front door. Re-run to refresh it.
  network.json        where each node is, and which commit each copy came from
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
import shutil
import subprocess
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


def commit_of(folder: Path) -> str:
    done = subprocess.run(["git", "-C", str(folder), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    dirty = subprocess.run(["git", "-C", str(folder), "status", "--porcelain", "--", "."], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL).stdout.strip()
    return (done.stdout.strip() or "unknown") + ("+uncommitted" if dirty else "")


def copy_package(source: Path, package: str, destination: Path) -> None:
    target = destination / package
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source / package, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def check() -> dict[str, object]:
    path = Path(plan()["config"]["data_dir"]) / "network.json"  # type: ignore[index]
    if not path.is_file():
        return {"ok": False, "problem": f"{path} is missing; run install_front_door.py"}
    config = json.loads(path.read_text(encoding="utf-8"))
    problems = [f"{name} is missing: {value}" for name, value in config.items()
                if name not in ("data_dir", "snapshots", "mode") and not Path(value).exists()]
    stale = []
    for name, info in (config.get("snapshots") or {}).items():
        now = commit_of(Path(info["source"]))
        if now != info["commit"]:
            stale.append(f"{name}: copy is from {info['commit']}, source is now {now}; re-run install_front_door.py")
    done = subprocess.run([sys.executable, str(Path(config["data_dir"]) / "bin" / "devnet.py"), "bootstrap"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    works = done.returncode == 0 and '"principles"' in done.stdout
    if not works:
        problems.append("`devnet bootstrap` failed: " + (done.stderr or done.stdout).strip()[:300])
    return {"ok": not problems and works, "mode": config.get("mode"), "problems": problems, "stale_copies": stale}


def plan(live: bool = False) -> dict[str, object]:
    sys.path.insert(0, str(HERE))
    from control_plane import DEFAULT_DATA_DIR, DEV_NETWORK_ROOT, FACTORY_ROOT
    from control_plane.front_door import epistemic_root
    from control_plane.network_registry import find_registry_root
    data = Path(DEFAULT_DATA_DIR)
    source_epistemic = Path(epistemic_root(DEV_NETWORK_ROOT))
    app = data / "app"
    config = {
        "network_root": str(DEV_NETWORK_ROOT),
        "control_plane_root": str(HERE if live else app / "control_plane_src"),
        "incubator_root": str(FACTORY_ROOT),
        "registry_root": str(find_registry_root(DEV_NETWORK_ROOT)),
        "epistemic_root": str(source_epistemic if live else app / "epistemic_src"),
        "data_dir": str(data),
        "mode": "live" if live else "snapshot",
    }
    if not live:
        config["snapshots"] = {  # type: ignore[assignment]
            "control_plane": {"source": str(HERE), "commit": commit_of(HERE)},
            "epistemic": {"source": str(source_epistemic), "commit": commit_of(source_epistemic)},
        }
    # In snapshot mode the copies do not exist until written; what must exist now are their sources.
    missing = [name for name, path in config.items() if isinstance(path, str) and name not in ("data_dir", "mode")
               and not Path(path).exists() and not (not live and name in ("control_plane_root", "epistemic_root"))]
    if not live:
        missing += [f"{name} source" for name, info in config["snapshots"].items() if not Path(info["source"]).exists()]  # type: ignore[union-attr]
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
    flags = argv if argv is not None else sys.argv[1:]
    if "--check" in flags:
        report = check()
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    show, live = "--show" in flags, "--live" in flags
    planned = plan(live)
    if not show:
        if not live:
            app = Path(planned["config"]["data_dir"]) / "app"  # type: ignore[index]
            copy_package(HERE, "control_plane", app / "control_plane_src")
            copy_package(Path(planned["config"]["snapshots"]["epistemic"]["source"]), "epistemic", app / "epistemic_src")  # type: ignore[index]
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
