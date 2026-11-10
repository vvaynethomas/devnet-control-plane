"""Pillar 1: Portfolio & Network discovery, Git state, and stewardship status."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import DEV_NETWORK_ROOT, FACTORY_ROOT
from .layout import iter_checkouts


def _parse_src_0013_baseline(factory_root: Path) -> dict[str, dict[str, str]]:
    """Extract the SRC-0013 portfolio audit table for baseline provenance."""
    src_path = factory_root / "knowledge" / "sources" / "SRC-0013-portfolio-rehabilitation-audit.md"
    baseline: dict[str, dict[str, str]] = {}
    if not src_path.is_file():
        return baseline
    row_re = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([0-9a-f]{7,40})`\s*\|\s*([^|]+?)\s*\|$"
    )
    for line in src_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = row_re.match(line.strip())
        if m:
            repo_name, visibility, captured_head, summary = m.groups()
            baseline[repo_name.lower()] = {
                "repo_name": repo_name,
                "visibility": visibility.strip(),
                "captured_head": captured_head.strip(),
                "audit_summary": summary.strip(),
                "provenance_id": "SRC-0013",
            }
    return baseline


def _load_factory_projects(factory_root: Path) -> list[dict[str, Any]]:
    reg_path = factory_root / "cockpit" / "project-registry.json"
    if not reg_path.is_file():
        return []
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        return data.get("entries", [])
    except Exception:
        return []


def _git_info(repo_dir: Path) -> dict[str, Any]:
    """Run fast, read-only local git commands on a repository directory."""
    info: dict[str, Any] = {
        "is_git": False,
        "branch": "—",
        "head_short": "—",
        "head_full": "",
        "last_commit_date": "—",
        "last_commit_subject": "",
        "modified_count": 0,
        "untracked_count": 0,
        "staged_count": 0,
        "state_label": "non-git",
    }
    git_marker = repo_dir / ".git"
    if not git_marker.exists():
        return info
    info["is_git"] = True
    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
        )
        if status_proc.returncode:
            info["state_label"] = "git-error"
        if status_proc.returncode == 0:
            lines = status_proc.stdout.splitlines()
            if lines and lines[0].startswith("## "):
                branch_part = lines[0][3:].split("...")[0].strip()
                info["branch"] = branch_part
            modified = 0
            untracked = 0
            staged = 0
            for line in lines[1:]:
                if not line:
                    continue
                xy = line[:2]
                if xy == "??":
                    untracked += 1
                else:
                    if xy[0] not in (" ", "?"):
                        staged += 1
                    if xy[1] not in (" ", "?"):
                        modified += 1
            info["modified_count"] = modified
            info["untracked_count"] = untracked
            info["staged_count"] = staged
            if modified == 0 and untracked == 0 and staged == 0:
                info["state_label"] = "clean"
            else:
                parts = []
                if staged:
                    parts.append(f"{staged} staged")
                if modified:
                    parts.append(f"{modified} modified")
                if untracked:
                    parts.append(f"{untracked} untracked")
                info["state_label"] = ", ".join(parts)

        log_proc = subprocess.run(
            ["git", "log", "-1", "--format=%H|%h|%ci|%s"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
        )
        if log_proc.returncode == 0 and log_proc.stdout.strip():
            parts = log_proc.stdout.strip().split("|", 3)
            if len(parts) == 4:
                info["head_full"] = parts[0]
                info["head_short"] = parts[1]
                info["last_commit_date"] = parts[2][:16]
                info["last_commit_subject"] = parts[3]
    except (OSError, subprocess.SubprocessError):
        info["state_label"] = "git-timeout-or-error"
    return info


def _stewardship_state(repo_dir: Path, is_factory: bool) -> dict[str, Any]:
    """Check stewardship / governance artifacts in a repository."""
    if is_factory:
        return {
            "role": "Incubator & Control Plane Host",
            "stewardship_tier": "factory-governed",
            "has_backlog": (repo_dir / "BACKLOG.md").is_file(),
            "has_roadmap": (repo_dir / "ROADMAP.md").is_file(),
            "has_agents": (repo_dir / ".github" / "agents").is_dir(),
            "has_skills": (repo_dir / ".github" / "skills").is_dir(),
        }
    has_backlog = (repo_dir / "BACKLOG.md").is_file()
    has_roadmap = (repo_dir / "ROADMAP.md").is_file()
    has_agents = (repo_dir / ".github" / "agents").is_dir()
    has_skills = (repo_dir / ".github" / "skills").is_dir()
    has_stewardship = (repo_dir / ".github" / "skills" / "repo-stewardship").is_dir()
    if has_backlog and (has_agents or has_skills):
        tier = "independent-kit"
        role = "Graduated / Kit-Equipped Product"
    elif has_backlog or (repo_dir / "README.md").is_file():
        tier = "standard-repo"
        role = "Portfolio Repository"
    else:
        tier = "minimal-checkout"
        role = "Local Checkout / Worktree"
    return {
        "role": role,
        "stewardship_tier": tier,
        "has_backlog": has_backlog,
        "has_roadmap": has_roadmap,
        "has_agents": has_agents,
        "has_skills": has_skills,
        "has_stewardship_skill": has_stewardship,
    }


def scan_portfolio(
    network_root: Path = DEV_NETWORK_ROOT,
    factory_root: Path = FACTORY_ROOT,
    include_worktrees: bool = False,
) -> dict[str, Any]:
    """Scan all repositories in the development network andincubated projects."""
    audit_baseline = _parse_src_0013_baseline(factory_root)
    # AIAD-ex12410 corresponds to product-incubator in SRC-0013
    if "product-incubator" in audit_baseline and "aiad-ex12410" not in audit_baseline:
        audit_baseline["aiad-ex12410"] = audit_baseline["product-incubator"]

    repositories: list[dict[str, Any]] = []
    dirs = iter_checkouts(network_root, include_worktrees=include_worktrees)
    if not dirs and not network_root.is_dir():
        dirs = [factory_root]

    for d in dirs:
        repo_name = (
            d.parent.name
            if d.name == "main" and d.parent.parent.name in {
                "devnet", "shared", "products", "research", "learning", "archive"
            }
            else d.name
        )
        is_factory = d.resolve() == factory_root.resolve()
        git = _git_info(d)
        stew = _stewardship_state(d, is_factory)
        audit = audit_baseline.get(repo_name.lower()) or audit_baseline.get(
            repo_name.lower().replace("vvaynethomas_", "")
        )
        readme_path = d / "README.md"
        backlog_path = d / "BACKLOG.md"
        repositories.append(
            {
                "name": repo_name,
                "path": str(d.resolve()),
                "is_factory": is_factory,
                "is_worktree_container": False,
                "git": git,
                "stewardship": stew,
                "audit": audit,
                "has_readme": readme_path.is_file(),
                "readme_path": str(readme_path.resolve()) if readme_path.is_file() else None,
                "backlog_path": str(backlog_path.resolve()) if backlog_path.is_file() else None,
            }
        )

    incubated_projects = _load_factory_projects(factory_root)
    enriched_projects: list[dict[str, Any]] = []
    for prj in incubated_projects:
        rel_path = prj.get("path", "")
        prj_readme = factory_root / rel_path if rel_path else None
        prj_dir = prj_readme.parent if prj_readme else None
        local_backlog = prj_dir / "BACKLOG.md" if prj_dir else None
        local_roadmap = prj_dir / "ROADMAP.md" if prj_dir else None
        enriched_projects.append(
            {
                **prj,
                "abs_path": str(prj_dir.resolve()) if prj_dir and prj_dir.exists() else None,
                "has_local_backlog": bool(local_backlog and local_backlog.is_file()),
                "local_backlog_rel": (
                    local_backlog.relative_to(factory_root).as_posix()
                    if local_backlog and local_backlog.is_file()
                    else None
                ),
                "has_local_roadmap": bool(local_roadmap and local_roadmap.is_file()),
            }
        )

    clean_count = sum(1 for r in repositories if r["git"]["state_label"] == "clean")
    dirty_count = sum(
        1 for r in repositories if r["git"]["is_git"] and r["git"]["state_label"] != "clean"
    )
    audited_count = sum(1 for r in repositories if r["audit"] is not None)

    return {
        "network_root": str(network_root),
        "factory_root": str(factory_root),
        "summary": {
            "total_repos": len(repositories),
            "clean_repos": clean_count,
            "dirty_repos": dirty_count,
            "audited_repos": audited_count,
            "incubated_projects": len(enriched_projects),
        },
        "repositories": repositories,
        "incubated_projects": enriched_projects,
    }


def open_repo_location(target_path: str, mode: str = "explorer") -> dict[str, Any]:
    """Open a local repository directory or file in Explorer or VS Code (explicit operator action)."""
    resolved = Path(target_path).resolve()
    if not resolved.exists():
        return {"ok": False, "error": f"Path does not exist: {resolved}"}
    try:
        if mode == "vscode":
            subprocess.Popen(["code", str(resolved)], shell=(os.name == "nt"))
            return {"ok": True, "mode": "vscode", "path": str(resolved)}
        if os.name == "nt":
            os.startfile(str(resolved))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(resolved)])
        return {"ok": True, "mode": "explorer", "path": str(resolved)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
