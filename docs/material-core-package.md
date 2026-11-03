# Material Core publication and consumer handover

The independent private repository is
[vvaynethomas/material-core](https://github.com/vvaynethomas/material-core).
[Release v0.1.1rc2](https://github.com/vvaynethomas/material-core/releases/tag/v0.1.1rc2)
points to `31d0661fae0a89f80290d8e645a6872431cd6dd6`. DNCP's standard metadata
and custom wheel metadata expose the immutable direct requirement only in the
optional `material` extra:

```text
material-core @ git+https://github.com/vvaynethomas/material-core@31d0661fae0a89f80290d8e645a6872431cd6dd6
```

The repository contains only the Python package, standalone tests, package
metadata, README and CHANGELOG. There is no DNCP registry, orchestration, UI,
storage, discovery, or repository-scanning dependency. DNCP no longer includes
the `material_core` sources; it retains its payload adapter and checks core
version 0.1.1rc2 and recorded source provenance explicitly. The public base package has no runtime dependencies
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
python -m pip install ".[material]"
```

The tag command is a convenience smoke check; DNCP pins the full commit rather
than trusting a movable tag. Missing repository access, missing package and
incompatible versions fail explicitly; there is no local-source fallback.

## Explicit fetch, then offline build/install

`build_material_core.py` is retained as a compatible command name but now only
downloads the producer's published v0.1.1rc2 and Utility Chest v0.1.0rc2 wheels,
never clones or rebuilds either
product. It requires authenticated GitHub access for this explicit fetch.
The independently pinned release wheel SHA-256 is
`c127e5529e2611da463dca683d0dd189e3fdcf7da6908427873fc7baf4a5dc47`; its
transitive Utility Chest commit is `4e2a06146944b438f10525ef45c44cc101b417b5`,
wheel SHA-256
`56ec8356007403ddf23a36bf17b06c0319dfb196fb0fd045995524d68a49e119`.
The command fails if either downloaded byte stream differs. A neighboring, self-edited
manifest cannot authorize another wheel with the same name/version.

```powershell
python build_material_core.py --output-dir dist\material-core
python release.py --material-core-wheel dist\material-core\material_core-0.1.1rc2-py3-none-any.whl --utility-wheel dist\material-core\utility_chest_credential_patterns-0.1.0rc2-py3-none-any.whl --output-dir dist\devnet
python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir dist\devnet-standard dist\devnet\devnet_control_plane-0.1.0.tar.gz
python install_material_core.py dist\material-core\material_core-0.1.1rc2-py3-none-any.whl --utility-wheel dist\material-core\utility_chest_credential_patterns-0.1.0rc2-py3-none-any.whl
python -m pip install --no-index --no-deps dist\devnet\devnet_control_plane-0.1.0-py3-none-any.whl
python -m pip check
```

For editable offline DNCP installation, install that core wheel with the
manifest-binding helper above, then use
`python -m pip install --no-index --no-build-isolation --no-deps -e .`.
Offline preinstallation makes the material capability available without
requesting the extra's Git fetch. `pip check` confirms base dependencies,
not optional capability availability or its source
commit. The helper's manifest records the verified source commits and wheel-derived source/
artifact hashes, while full builds record both pinned producer wheel digests and immutable source
requirement. Preserve those manifests for offline provenance.

The offline installer verifies one in-memory byte snapshot against the
independently pinned producer release digest, installs a temporary wheel made
from that exact snapshot, and checks installed processor hashes derived from
those verified bytes. It records artifact/source evidence in the installed
distribution. A bare local wheel install without this evidence
is refused by DNCP rather than assigned a guessed Git commit.

Both supported paths load only files owned by the checked distribution under a
private module namespace. Ordinary `material_core` imports and preloaded modules
are not used by DNCP. Authenticated Git installs verify PEP 610 version/source
provenance, not post-install byte integrity. The offline path checks file hashes
against evidence derived from the independently digest-pinned wheel at load time;
this is not a signed publisher attestation, and local evidence can be modified.
Neither path claims
protection against an attacker who can alter the installed distribution and its
evidence. The process caches its checked core, so reload after intentional updates.

## Combined optional consumers

The `conversation-hub` extra independently pins v0.1.2 at
`381644edec4c948375bc6f24b695bbba7b699e7a`, marker-gated to Python >=3.12;
its published wheel SHA-256 is
`537dd2fc8f792742d64fd6377b3fa706af8fb2d8f2af7b491dbe5a82a30237c1`.
It does not install Material Core, and the `material` extra does not install Hub.
Install both explicitly on Python >=3.12 with:

```powershell
python -m pip install ".[material,conversation-hub]"
```

The base remains Python >=3.10. On 3.10/3.11 the Hub dependency marker is inactive;
attempting its command still fails explicitly with Python 3.12+ guidance.
Hub retains its distribution-owned, shadow-safe reader and PEP 610 source
provenance check. The published Hub wheel SHA-256 above is producer evidence;
the running consumer does not enforce that wheel digest or installed-file
integrity. See [the conversation consumer contract](conversation-library-consumer.md).
Both custom and standard wheel builders preserve these independent pins/markers.
The isolated matrix test `test_consumer_extras.py` verifies each extra and both
with real private dependencies and synthetic data. All tests downloading private
artifacts or installing private Git dependencies require explicit
`DNCP_PRIVATE_INTEGRATION=1`; otherwise they skip with a clear reason. Public
base and substitution/refusal tests remain hermetic. Format/digester tests skip
when the optional core is absent, not by fetching it. For authenticated coverage:

```powershell
$env:DNCP_PRIVATE_INTEGRATION = "1"
python -m unittest discover -s tests -p test_consumer_extras.py -v
python -m unittest discover -s tests -p test_material_core_package.py -v
python -m unittest discover -s tests -p test_phone_home_package.py -v
```

Local validation used Python
3.14; no 3.10/3.11 interpreter was installed. Marker evaluations for those versions
are tested, but that is not a substitute for runtime tests on those interpreters.

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
