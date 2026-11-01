"""Development Network Control Plane (DNCP) and Interaction Frame Lab."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_VERSION = "0.1.0"

# Root of this project/package
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Embedded registry vs. project registry
PACKAGE_REGISTRY = Path(__file__).resolve().parent / "registry" / "interaction_frames.json"
PROJECT_REGISTRY = PROJECT_ROOT / "registry" / "interaction_frames.json"
REGISTRY_PATH = PROJECT_REGISTRY if PROJECT_REGISTRY.is_file() else PACKAGE_REGISTRY


def find_network_root(start_dir: Path | None = None) -> Path:
    """Discover the development network root containing sibling repositories."""
    if "DEV_NETWORK_ROOT" in os.environ:
        return Path(os.environ["DEV_NETWORK_ROOT"]).resolve()
    curr = (start_dir or Path.cwd()).resolve()
    for p in [curr, *curr.parents]:
        if p.name == "GitHub-Repos":
            return p
    for p in [PROJECT_ROOT, *PROJECT_ROOT.parents]:
        if p.name == "GitHub-Repos":
            return p
    return PROJECT_ROOT.parent


def find_factory_root(network_root: Path | None = None) -> Path:
    """Discover incubator factory root containing knowledge graph and cockpit."""
    if "FACTORY_ROOT" in os.environ:
        return Path(os.environ["FACTORY_ROOT"]).resolve()
    net = network_root or find_network_root()
    for candidate in [net / "AIAD-ex12410", net / "product-incubator"]:
        if (candidate / "cockpit" / "project-registry.json").is_file():
            return candidate
    curr = Path.cwd().resolve()
    for p in [curr, *curr.parents]:
        if (p / "cockpit" / "project-registry.json").is_file() or (p / "knowledge").is_dir():
            return p
    return curr


def find_default_data_dir() -> Path:
    if "DEVNET_DATA_DIR" in os.environ:
        return Path(os.environ["DEVNET_DATA_DIR"]).resolve()
    return PROJECT_ROOT / "data"


DEV_NETWORK_ROOT = find_network_root()
FACTORY_ROOT = find_factory_root(DEV_NETWORK_ROOT)
DEFAULT_DATA_DIR = find_default_data_dir()
