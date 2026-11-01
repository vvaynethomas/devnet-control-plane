"""Small material-neutral contract for explicit, provisional digestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

DISPOSITIONS = (
    "maps to existing capability",
    "trusted solution to adopt",
    "extend/customize/integrate",
    "new knowledge/idea",
)
REVIEW_ACTIONS = (*DISPOSITIONS, "defer", "reject")
NOTICE = (
    "All candidates are provisional. Only a human chooses a disposition; "
    "no promotion, adoption, dispatch or canonical write occurs. "
    "A missing match does not prove novelty; a match does not establish trust."
)


@dataclass(frozen=True)
class MaterialReference:
    kind: str
    identity: str
    revision: str
    location: str


@dataclass
class Digestion:
    material: MaterialReference
    extractors: list[dict[str, str]]
    items: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=lambda: {
        "gaps": [], "exclusions": [], "errors": [],
    })
    residue: dict[str, Any] = field(default_factory=lambda: {
        "not_targeted": [], "frequency": [],
    })
    schema_version: int = 1
    notice: str = NOTICE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Digester(Protocol):
    """Extraction only: no registration, routing, review or promotion side effects."""

    def digest(self, material: MaterialReference) -> Digestion: ...
