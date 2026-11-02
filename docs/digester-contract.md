# Digester contract v1

`control_plane\digester.py` defines the repo-agnostic
`Digester.digest(MaterialReference, target="") -> Digestion` protocol.
It extracts provisional evidence only. Registration, explicit invocation,
inventory comparison, human dispositions and persistence are outside it.
Explicitly supplied text/Markdown, CSV, HTML, Python and ZIP use
`SuppliedMaterialDigester` in `control_plane\material_ingestion.py`; see
[coverage and limits](material-ingestion.md). No router or concierge is implemented.

The repository implementation is `RepositoryDigester` in
`control_plane\repo_metabolizer.py`. `RepositoryMetabolizer` supplies opt-in
registration and explicit scans through the existing `devnet digest` CLI.
It retains only consent metadata in `digester.sqlite`, not scan bundles, review
events or source copies. There is no second CLI or competing review store.

## Shared result

| Field | Contract |
|---|---|
| `schema_version` | Integer `1`; the provisional shape reconciles the two unmerged implementations. |
| `material` | `kind`, `identity`, immutable `revision`, local `location`. Repository scans use the registered root as identity and an exact Git commit as revision; no inferred remote identity or fetch. |
| `extractors` | Names and semantic versions of the extraction pipeline, plus package/Git versions. Repository static extraction is version `2`; parsing/ID/residue semantics changed during reconciliation. |
| `items` | Ordered provisional observations, with deterministic IDs, category/title/detail, truncation flags, provenance and target-match indicator. A symbol is not necessarily reusable; a heading is a topic, not a decision. |
| `file_evidence` | Read-file path, revision, material identity, Git blob, SHA-256, byte size, extractor/version and literal evidence reference. |
| `coverage` | Implementation-specific counts, limits, omissions and errors. The repository result includes counted exclusions and bounded omitted-file evidence; overflow is counted explicitly. Full repository coverage is always false. |
| `residue` | Bounded notable untargeted and repeated observations, with normalized full-text hash, truncated display text, occurrence count and evidence. Distinct texts sharing a display prefix are not merged. |
| `target` | Optional human focus. It flags items and prioritizes comparison; it does not discard untargeted candidates. |
| `notice` | Human-only boundary, no-match/novelty and similarity/trust caveats. |

Repository provenance identifies the exact source commit/blob and line or
file-level location precision. Errors do not echo parser/source snippets.
Pure extraction is deterministic for the same material, target and extractor
context. It does not access SQLite, query inventories, instantiate phone-home,
write source files, or add observation timestamps.

The orchestration envelope adds `comparison`, `review`, `evidence_digest` and
`observed_at`. The digest excludes the timestamp but includes comparison context.
Matching-root, canonical-only existing Fabric caches are advisory; missing,
corrupt, wrong-root, legacy and conversation-containing caches are not searched.
There are no implicit rebuilds or live inventory scans. Comparison exposes
freshness, incomplete graph coverage, errors, evidence and text relevance.
No match never establishes novelty; a match never establishes trust.

The four dispositions are exactly:

1. maps to existing capability
2. trusted solution to adopt
3. extend/customize/integrate
4. new knowledge/idea

`defer` and `reject` are additional review actions, not dispositions.
Options are returned for human review only; no automatic classification,
promotion, adoption, dispatch, canonical write or phone-home submission occurs.
The destination product owns its library; the incubator is optional.

## Repository extraction boundaries

Repository-only registration validates the root but does not read HEAD/tree/blobs or start a
scan. An explicit scan checks opt-in before repository observation, resolves
`HEAD` or `--revision` once, and reads committed tree/blobs without checkout.
Dirty/untracked files, hooks, filters, install scripts, dependency resolution,
submodule traversal, symlink dereferencing, lazy fetch and credential prompting
are excluded. Missing local objects produce visible failures.

The standard-library extractors cover top-level public Python symbols/module
docstrings, Markdown headings and notable lines outside fenced code, validated
JSON dependency manifests, simple requirements declarations, and bounded static
TOML/Go/configuration evidence. JSON duplicate keys and non-string dependency
versions fail visibly. Requirements directives are not fetched. Python private
symbols/imports, untargeted bodies/manifest fields/document regions, unsupported
files and repeated candidate titles remain residue. Repeated candidates retain
distinct evidence and IDs rather than being deduplicated. Frequency counts are
observations, not independent implementations or corroboration.

Limits remain 1 MiB tree output, 100 files, 128 KiB per file, 1 MiB content,
100 items, 1,000 observations, 30 residue groups, three references per group,
300 residue display characters and 100 omitted-file references. Comparison is
separately capped at ten queries/five matches. Overflows have counted omissions;
tree overflow refuses the scan rather than returning partial success.

Source access is read-only. Runtime consent storage must be outside Git
repositories and the configured inventory root; storage checks repeat on use.
Recognized credential-bearing content and sensitive filenames are excluded.
This is incomplete secret detection, not authorization to share a bundle.
No full source copies or scan history are retained unless the human explicitly
redirects JSON to a local review file. No LLM, external extractor, watcher,
automatic scan or phone-home dependency is required for repository digestion.

## Supplied material orchestration

Explicit material requires no repo opt-in, product membership, bilateral
acceptance or report metadata. One `PhoneHome.submit(kind="material", ...)`
digests the supplied bytes with the same shared result contract and stores
bounded evidence in the existing local inbox. The pure digester does not
instantiate phone-home, compare inventories or persist anything. Material
revisions are SHA-256 of exact input bytes; original identity and location stay
input provenance, not canonical identifiers. Residue includes untargeted content
and repeated observation counts, never automatic waste classification.

The phone-home receipt adds ingestion time, idempotency and content digest plus
an explicit no-second-acceptance review boundary. Its provisional status is not
a pending ingest approval; only consequential later execution, adoption or
canonical promotion requires a human. Raw bytes/base64 are not stored, but bounded
evidence snippets are. No automatic inventory scan, promotion or external
transmission is introduced. Repository opt-in continues to gate whole-repo scans
only; the repository-specific limits above do not apply to supplied material.
