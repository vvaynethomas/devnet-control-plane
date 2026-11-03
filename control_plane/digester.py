"""Compatibility exports for the reusable, material-neutral core contract."""

from .material_capability import require_material_core

require_material_core()

from material_core.contract import (
    DISPOSITIONS,
    NOTICE,
    REVIEW_ACTIONS,
    Digestion,
    Digester,
    MaterialReference,
)

__all__ = [
    "DISPOSITIONS",
    "NOTICE",
    "REVIEW_ACTIONS",
    "Digestion",
    "Digester",
    "MaterialReference",
]
