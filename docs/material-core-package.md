# Material Core publication and consumer handover

The independent private repository is
[vvaynethomas/material-core](https://github.com/vvaynethomas/material-core).
[Release v0.1.0](https://github.com/vvaynethomas/material-core/releases/tag/v0.1.0)
points to `108fe9f309005ac7593fd640fce54bc196262198`. DNCP's standard metadata
and custom wheel metadata expose the immutable direct requirement only in the
optional `material` extra:

```text
material-core @ git+https://github.com/vvaynethomas/material-core@108fe9f309005ac7593fd640fce54bc196262198
```

The repository contains only the Python package, standalone tests, package
metadata, README and CHANGELOG. There is no DNCP registry, orchestration, UI,
storage, discovery, or repository-scanning dependency. DNCP no longer includes
the `material_core` sources; it retains its payload adapter and checks core
version 0.1.0 explicitly. The public base package has no runtime dependencies
and needs no private credentials. Fabric credential filtering and MCP schema
description are DNCP-owned and independent of the processor.

## Public base installation

```powershell
python -m pip install --no-index --no-build-isolation .
python release.py --output-dir dist\devnet
python -m pip install --no-index dist\devnet\devnet_control_plane-0.1.0-py3-none-any.whl
```

Source builds require locally installed setuptools/wheel. CLI help/version,
UI health, Fabric and non-material phone-home operations work without the
core. Material submission/CLI ingestion and repository digestion require the
extra; unavailable or incompatible processors produce actionable errors
(HTTP/MCP status 503) without discarding input or writing a failed submission.

## Authenticated installation

Use an authenticated Git credential helper, never a token embedded in a URL:

```powershell
python -m pip install git+https://github.com/vvaynethomas/material-core@v0.1.0
python -m pip install ".[material]"
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
Offline preinstallation makes the material capability available without
requesting the extra's Git fetch. `pip check` confirms base dependencies,
not optional capability availability or its source
commit. The helper's manifest records the verified source commit and source/
artifact hashes, while full builds record the core wheel digest and immutable source
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
