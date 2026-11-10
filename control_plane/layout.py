"""Discover primary checkouts in both legacy and categorized layouts."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


CATEGORIES = ("devnet", "shared", "products", "research", "learning", "archive")
WORKTREE_CONTAINERS = ("copilot-worktrees",)


def _is_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def _primary_inside_container(container: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirs, _files in os.walk(container, followlinks=False):
        here = Path(current)
        dirs[:] = [
            name for name in dirs
            if name != ".git" and not (here / name).is_symlink()
            and not getattr(here / name, "is_junction", lambda: False)()
        ]
        marker = here / ".git"
        if marker.is_dir():
            result = subprocess.run(
                ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            if result.returncode == 0 and Path(result.stdout.strip()).resolve() == marker.resolve():
                found.append(here)
            dirs[:] = []
    return found


def iter_primary_checkouts(network_root: Path) -> list[Path]:
    """Return unique primary checkouts, without treating container names as ownership."""
    roots: dict[str, Path] = {}

    def add(path: Path) -> None:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return
        if _is_checkout(path):
            resolved = path.resolve()
            roots[os.path.normcase(str(resolved))] = resolved

    if not network_root.is_dir():
        return []

    for entry in network_root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in CATEGORIES:
            for project in entry.iterdir():
                if project.is_dir() and not project.name.startswith("."):
                    add(project / "main")
        elif entry.name.endswith("-worktrees") or entry.name in WORKTREE_CONTAINERS:
            for primary in _primary_inside_container(entry):
                add(primary)
        else:
            add(entry)

    return sorted(roots.values(), key=lambda path: str(path).lower())


def iter_checkouts(network_root: Path, include_worktrees: bool = False) -> list[Path]:
    """Return primary repositories and, optionally, registered linked worktrees."""
    primary = iter_primary_checkouts(network_root)
    if not include_worktrees:
        return primary

    checkouts: dict[str, Path] = {os.path.normcase(str(path.resolve())): path for path in primary}
    for repository in primary:
        probe = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if probe.returncode:
            continue
        result = subprocess.run(
            ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        if result.returncode:
            raise RuntimeError(
                f"Unable to list registered worktrees for {repository}: {result.stderr.strip()}"
            )
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree "):])
                checkouts[os.path.normcase(str(path.resolve()))] = path
    return sorted(checkouts.values(), key=lambda path: str(path).lower())


def main_checkout(network_root: Path, repository_name: str) -> Path | None:
    """Resolve a repository by preserved checkout name in legacy or categorized layout."""
    matches = [
        path for path in iter_primary_checkouts(network_root)
        if path.name.casefold() == repository_name.casefold()
        or path.parent.name.casefold() == repository_name.casefold()
    ]
    if not matches:
        return None
    return matches[0]
