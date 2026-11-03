# Material Core 0.1.0

`material-core` is a small Python library for deterministic, bounded processing
of explicitly supplied bytes. `material_core.digest_material(...)` returns a
provisional evidence bundle; it does not discover sources, make network calls,
execute supplied content, compare inventories, or persist results.

The source was separated from DNCP commit
`c57d6157fcb87db3eea3f736832cbb1a061cebc4`. The source was distributed as part
of DNCP's project metadata declaring MIT. No separate license file or independent
license/ownership approval is established by this packaging change; confirm
those before publishing or transferring this distribution.

Build a wheel and source archive locally from this checkout:

```powershell
python build_material_core.py --output-dir dist\material-core
```

Install only the locally built version:

```powershell
python -m pip install --no-index --find-links dist\material-core material-core==0.1.0
```

The accompanying `RELEASE_MANIFEST.json` records source and artifact SHA-256
identities. Artifacts are local build outputs, not published releases.
