# Material Core package handover

## Separate artifacts and pin

`material_core\` is a separately buildable Python distribution named
`material-core`, version `0.1.0`, requiring Python 3.10 or later and no runtime
dependencies. DNCP's `pyproject.toml` pins `material-core==0.1.0`; its
`control_plane\material_ingestion.py` also checks the imported core version and
fails loudly if it is not exactly `0.1.0`. DNCP wheels and sdists do not contain
a copy of the `material_core` package.

Build both core artifacts offline from this source checkout:

```powershell
python build_material_core.py --output-dir dist\material-core
```

Artifacts:

- `dist\material-core\material_core-0.1.0-py3-none-any.whl`
- `dist\material-core\material_core-0.1.0.tar.gz`
- `dist\material-core\RELEASE_MANIFEST.json`

The builder creates its wheel from the source archive with `pip wheel
--no-deps --no-index --no-build-isolation`. It requires locally installed
setuptools and wheel; it does not fetch build dependencies.

Install the core by itself in an offline environment:

```powershell
python -m pip install --no-index --find-links dist\material-core material-core==0.1.0
```

Consumer application development install:

```powershell
python -m pip install --no-index --no-build-isolation --find-links dist\material-core -e .
```

Build DNCP's custom artifacts only when the exact core wheel is supplied:

```powershell
python release.py --material-core-wheel dist\material-core\material_core-0.1.0-py3-none-any.whl --output-dir dist\devnet
```

`release.py` rejects a missing, malformed, incomplete, or differently versioned
core wheel. Its manifest records the pinned filename, version, byte size and
SHA-256. Install DNCP and resolve that dependency solely from the local wheelhouse:

```powershell
python -m pip install --no-index --find-links dist\material-core dist\devnet\devnet_control_plane-0.1.0-py3-none-any.whl
```

The ordinary setuptools wheel built from DNCP's source archive has the same
`Requires-Dist: material-core==0.1.0` metadata and uses the same local `--find-links`
install process. Build that wheel without dependency downloads with:

```powershell
python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir dist\devnet-standard dist\devnet\devnet_control_plane-0.1.0.tar.gz
```

## Boundary and evidence

`material_core.digest_material(raw, name=..., format=..., identity=...,
target=...)` and `SuppliedMaterialDigester` process explicit bytes only.
Contract types are in `material_core\contract.py`; the safety token pattern is
in `material_core\safety.py`. There is no network, source discovery, execution,
DNCP import, registry/runtime setup, inventory comparison, or persistence in
the core package. Its evidence format preserves the existing extractor name,
provenance, gaps, refusals, caps and supported format behavior.

`build_material_core.py` emits the standalone wheel, source archive, and a
manifest with source digests, build-source commit, artifact digests and sizes.
DNCP's manifest independently records the exact core wheel digest it was built
against. Current local artifact paths are under `dist\material-core\` and
`dist\devnet\`; these build outputs are git-ignored and are not published
releases. Rebuild them from the committed source before distributing.

The source was separated from DNCP commit
`c57d6157fcb87db3eea3f736832cbb1a061cebc4`, whose package metadata declares MIT.
No independent license file, ownership transfer, or approval to publish this
distribution is established here. Preserve source provenance and resolve those
owner decisions before any external publication. This package split does not
make DNCP-specific whole-repository scanning portable: Git revision access,
registration, opt-in and cached Fabric comparison remain in
`control_plane\repo_metabolizer.py`.
