# Material Core publication and consumer handover

The independent private repository is
[vvaynethomas/material-core](https://github.com/vvaynethomas/material-core).
[Release v0.1.0](https://github.com/vvaynethomas/material-core/releases/tag/v0.1.0)
points to `108fe9f309005ac7593fd640fce54bc196262198`. DNCP's standard metadata
and custom wheel metadata use the immutable direct requirement:

```text
material-core @ git+https://github.com/vvaynethomas/material-core@108fe9f309005ac7593fd640fce54bc196262198
```

The repository contains only the Python package, standalone tests, package
metadata, README and CHANGELOG. There is no DNCP registry, orchestration, UI,
storage, discovery, or repository-scanning dependency. DNCP no longer includes
the `material_core` sources; it retains its payload adapter and checks core
version 0.1.0 explicitly.

## Authenticated installation

Use an authenticated Git credential helper, never a token embedded in a URL:

```powershell
python -m pip install git+https://github.com/vvaynethomas/material-core@v0.1.0
python -m pip install .
```

The tag command is a convenience smoke check; DNCP pins the full commit rather
than trusting a movable tag. Missing repository access, missing package and
incompatible versions fail explicitly; there is no local-source fallback.

## Explicit fetch, then offline build/install

`build_material_core.py` now fetches only the immutable external repository
commit and builds a wheel and source archive. It requires authenticated GitHub
access for that explicit fetch and locally installed setuptools/wheel. Package
tests exercising this helper also require that access. It does not download
build dependencies or use an in-tree implementation.

```powershell
python build_material_core.py --output-dir dist\material-core
python release.py --material-core-wheel dist\material-core\material_core-0.1.0-py3-none-any.whl --output-dir dist\devnet
python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir dist\devnet-standard dist\devnet\devnet_control_plane-0.1.0.tar.gz
python -m pip install --no-index dist\material-core\material_core-0.1.0-py3-none-any.whl
python -m pip install --no-index --no-deps dist\devnet\devnet_control_plane-0.1.0-py3-none-any.whl
python -m pip check
```

For editable offline DNCP installation, preinstall that core wheel, then use
`python -m pip install --no-index --no-build-isolation --no-deps -e .`.
`--no-deps` is necessary because a direct Git requirement cannot be resolved
from `--find-links`; `pip check` confirms the installed version, not its source
commit. The helper's manifest records the verified source commit and source/
artifact hashes, while DNCP records the core wheel digest and immutable source
requirement. Preserve those manifests for offline provenance.

## Scope and approval limits

`material_core.digest_material(...)` processes explicit bytes only, preserving
supported formats, provenance, scalar fidelity, gaps, refusals and caps.
DNCP retains network intake, inbox persistence, Git revision access, registration,
opt-in scanning and cached Fabric comparison in its own modules.

The clean initial core commit cites DNCP source commit
`c57d6157fcb87db3eea3f736832cbb1a061cebc4` and packaging commit
`1cbadfa9b4476dc4316099418e153b6aabf8b2fd`. Originating DNCP metadata declared
MIT; independent licensing/ownership remain undecided. No license file or new
license grant was added, and this private release does not authorize public
redistribution or ownership transfer.
