"""Install the digest-pinned alm-lifecycle-core wheel offline and bind installed-byte evidence."""

import argparse
from pathlib import Path

from install_material_core import _install_verified
from release import verify_alm_bytes


def install(wheel: Path) -> None:
    data = wheel.read_bytes()
    _install_verified(data, wheel.name, verify_alm_bytes(data, wheel.name), "alm-lifecycle-core")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    install(parser.parse_args().wheel)
