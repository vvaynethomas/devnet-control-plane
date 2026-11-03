"""Load distribution-owned Python modules from an already checked source snapshot."""

from __future__ import annotations

from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
import hashlib
from pathlib import Path
from pathlib import PurePosixPath
import sys
import threading
from types import ModuleType
from typing import Mapping


SNAPSHOT_LOAD_LOCK = threading.RLock()


class _SourceBytesLoader(Loader):
    def __init__(self, fullname: str, filename: Path, source: bytes, is_package: bool) -> None:
        self.fullname = fullname
        self.filename = filename
        self.source = source
        self.is_package = is_package

    def create_module(self, spec: ModuleSpec) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.__file__ = str(self.filename)
        if self.is_package:
            module.__path__ = []
        code = compile(self.source, str(self.filename), "exec", dont_inherit=True)
        exec(code, module.__dict__)


class _SnapshotFinder(MetaPathFinder):
    def __init__(self, namespace: str, sources: Mapping[str, tuple[Path, bytes]]) -> None:
        self.namespace = namespace
        self.sources = sources

    def find_spec(self, fullname: str, path=None, target=None) -> ModuleSpec | None:
        if fullname == self.namespace:
            relative = "__init__.py"
        elif fullname.startswith(self.namespace + "."):
            stem = fullname[len(self.namespace) + 1:].replace(".", "/")
            relative = f"{stem}/__init__.py" if f"{stem}/__init__.py" in self.sources else f"{stem}.py"
        else:
            return None
        entry = self.sources.get(relative)
        if entry is None:
            raise ModuleNotFoundError(
                f"No verified source exists for {fullname!r}",
                name=fullname,
            )
        filename, source = entry
        is_package = relative == "__init__.py" or relative.endswith("/__init__.py")
        loader = _SourceBytesLoader(fullname, filename, source, is_package)
        return ModuleSpec(
            fullname,
            loader,
            origin=str(filename),
            is_package=is_package,
        )


def load_package_from_snapshot(
    package: str,
    namespace: str,
    sources: Mapping[str, tuple[Path, bytes]],
) -> ModuleType:
    """Execute package code only from captured, caller-verified source bytes."""
    with SNAPSHOT_LOAD_LOCK:
        init = sources.get("__init__.py")
        if init is None:
            raise ImportError(f"Verified package {package} is missing __init__.py")

        unload_package_snapshot(namespace)
        finder = _SnapshotFinder(namespace, sources)
        root_spec = finder.find_spec(namespace)
        if root_spec is None or root_spec.loader is None:
            raise ImportError(f"Verified package {package} has no source loader")
        module = ModuleType(namespace)
        module.__package__ = namespace
        module.__path__ = []
        module.__file__ = str(init[0])
        module.__spec__ = root_spec
        sys.modules[namespace] = module
        sys.meta_path.insert(0, finder)
        try:
            root_spec.loader.exec_module(module)
        except BaseException:
            unload_package_snapshot(namespace)
            raise
        return module


def unload_package_snapshot(namespace: str) -> None:
    with SNAPSHOT_LOAD_LOCK:
        for name in tuple(sys.modules):
            if name == namespace or name.startswith(namespace + "."):
                del sys.modules[name]
        for finder in tuple(sys.meta_path):
            if isinstance(finder, _SnapshotFinder) and finder.namespace == namespace:
                sys.meta_path.remove(finder)


def capture_distribution_sources(
    installed,
    package: str,
    required: set[str],
    expected_hashes: Mapping[str, str] | None = None,
) -> dict[str, tuple[Path, bytes]]:
    owned = {str(item).replace("\\", "/") for item in (installed.files or ())}
    package_prefix = package + "/"
    source_paths = sorted(
        name for name in owned if name.startswith(package_prefix) and name.endswith(".py")
    )
    for relative in source_paths:
        suffix = relative[len(package_prefix):]
        parsed = PurePosixPath(suffix)
        if (not parsed.parts or parsed.is_absolute() or parsed.as_posix() != suffix
                or any(part in ("", ".", "..") for part in parsed.parts)):
            raise ValueError(f"{package} has an invalid owned source path")
    if not required <= set(source_paths):
        raise ValueError(f"{package} is missing an owned source module")
    if expected_hashes is not None and set(expected_hashes) != set(source_paths):
        raise ValueError(f"{package} source evidence is incomplete")

    root = Path(installed.locate_file("")).resolve()
    captured: dict[str, tuple[Path, bytes]] = {}
    for relative in source_paths:
        path = Path(installed.locate_file(relative)).resolve()
        path.relative_to(root)
        if not path.is_file():
            raise ValueError(f"{package} source module is missing")
        source = path.read_bytes()
        if expected_hashes is not None:
            if hashlib.sha256(source).hexdigest() != expected_hashes[relative]:
                raise ValueError(f"{package} source bytes differ from verified evidence")
        captured[relative[len(package_prefix):]] = (path, source)
    return captured
