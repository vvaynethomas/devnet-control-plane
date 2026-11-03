"""Optional material capability availability and DNCP transport contract."""

import importlib

CORE_VERSION = "0.1.0"
CORE_COMMIT = "108fe9f309005ac7593fd640fce54bc196262198"
FORMATS = ("text", "markdown", "csv", "html", "json", "python", "zip")
INSTALL_GUIDANCE = (
    'Install with authenticated private repository access: '
    'pip install "devnet-control-plane[material]". '
    f"Required material-core=={CORE_VERSION} at commit {CORE_COMMIT}."
)


class MaterialCapabilityError(ValueError):
    status = 503


def require_material_core():
    try:
        core = importlib.import_module("material_core")
    except ModuleNotFoundError as exc:
        if exc.name != "material_core":
            raise
        raise MaterialCapabilityError("Material capability is not installed. " + INSTALL_GUIDANCE) from exc
    if core.__version__ != CORE_VERSION:
        raise MaterialCapabilityError(
            f"DNCP requires material-core=={CORE_VERSION}; found {core.__version__}. " + INSTALL_GUIDANCE
        )
    return core
