from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from control_plane import find_factory_root
from control_plane.layout import iter_checkouts, iter_primary_checkouts, main_checkout
from control_plane.portfolio import scan_portfolio


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class TestRepositoryLayout(unittest.TestCase):
    def test_discovers_legacy_and_project_contained_primary_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy-repo"
            categorized = root / "shared" / "sample-lib" / "main"
            independent = root / "old-worktrees" / "independent-clone"
            for path in (legacy, categorized, independent):
                path.mkdir(parents=True)
                git(path, "init", "-q")

            found = iter_primary_checkouts(root)
            self.assertEqual(
                {path.resolve() for path in found},
                {legacy.resolve(), categorized.resolve(), independent.resolve()},
            )
            self.assertEqual(main_checkout(root, "sample-lib"), categorized.resolve())

    def test_finds_factory_inside_devnet_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = root / "devnet" / "AIAD-ex12410" / "main"
            registry = factory / "cockpit" / "project-registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text('{"entries": []}', encoding="utf-8")
            self.assertEqual(find_factory_root(root), factory.resolve())

    def test_includes_only_git_registered_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "products" / "sample-app" / "main"
            primary.mkdir(parents=True)
            git(primary, "init", "-q", "-b", "main")
            git(primary, "config", "user.name", "Migration Test")
            git(primary, "config", "user.email", "migration-test@example.invalid")
            (primary / "README.md").write_text("sample\n", encoding="utf-8")
            git(primary, "add", "README.md")
            git(primary, "commit", "-q", "-m", "initial")
            worktree = root / "copilot-worktrees" / "sample-app" / "feature"
            worktree.parent.mkdir(parents=True)
            git(primary, "worktree", "add", "-q", "-b", "feature", str(worktree))

            primary_only = iter_checkouts(root)
            all_checkouts = iter_checkouts(root, include_worktrees=True)
            self.assertEqual([path.resolve() for path in primary_only], [primary.resolve()])
            self.assertEqual(
                {path.resolve() for path in all_checkouts},
                {primary.resolve(), worktree.resolve()},
            )

    def test_portfolio_uses_project_name_for_contained_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "products" / "sample-app" / "main"
            primary.mkdir(parents=True)
            git(primary, "init", "-q", "-b", "main")
            result = scan_portfolio(root, root / "missing-factory")
            self.assertEqual([repo["name"] for repo in result["repositories"]], ["sample-app"])
            self.assertEqual(result["repositories"][0]["path"], str(primary.resolve()))


if __name__ == "__main__":
    unittest.main()
