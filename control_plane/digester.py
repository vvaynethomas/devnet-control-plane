"""Compatibility exports for the reusable, material-neutral core contract."""

from .material_capability import require_material_core

_core = require_material_core()
DISPOSITIONS = _core.DISPOSITIONS
NOTICE = _core.NOTICE
REVIEW_ACTIONS = _core.REVIEW_ACTIONS
Digestion = _core.Digestion
Digester = _core.Digester
MaterialReference = _core.MaterialReference

__all__ = [
    "DISPOSITIONS",
    "NOTICE",
    "REVIEW_ACTIONS",
    "Digestion",
    "Digester",
    "MaterialReference",
]
