# Digester contract v1

DNCP's repository metabolizer is the first implementation of a small
material-neutral `Digester` protocol (`control_plane\digester.py`).
`digest(MaterialReference) -> Digestion` extracts evidence only. Eligibility,
explicit invocation, storage, inventory comparison and human review sit outside
the protocol. Other material types can implement it later; no other digester or
router is implemented here.

## Bundle

| Field | Contract |
|---|---|
| `schema_version` | Integer `1`. |
| `material` | `kind`, stable human-supplied `identity`, immutable `revision`, local `location`. For repositories: exact Git commit, registered top-level checkout, and repository identity. No remote is fetched or inferred from a folder name. |
| `extractors` | Names and independent versions of every extractor attempted. Versions change when extraction semantics change. |
| `items` | Ordered provisional observations with stable `id`, `kind`, `title`, bounded `summary`, `status: provisional`, four `dispositions`, and `evidence`. |
| `evidence` | Exact material identity/revision, path, blob identifier, line (or null for whole-file evidence), extractor name/version. No assertion that a symbol is reusable, a heading is a decision, or a dependency is trustworthy. |
| `coverage` | `gaps`, `exclusions`, `errors` are always arrays, even when empty. Counts and configured limits distinguish inventory from actually read/extracted files. Every omitted file/region has a reason. |
| `residue.not_targeted` | Notable material outside the current extraction: unsupported files, documentation without headings, imports/private symbols and non-targeted manifest fields. Keep evidence and counts, not full source copies. This is remainder for later human investigation, not discarded noise or another candidate classification. |
| `residue.frequency` | Repeated observations with `section` (`items` or `not_targeted`), `kind`, normalized `title`, `count`, and evidence for each occurrence. Remainder summaries act as titles; counts refer to observation occurrences, not lines of code or dependency versions. Counts preserve commonality/redundancy signals; repetition neither proves independent implementations nor increases trust. Candidates are not deduplicated away. |
| `notice` | Provisional/human-only boundary and explicit missing-match/false-trust warning. |

The repository implementation adds `comparison` to each item: query, candidate
matches, evidence/path, and match rationale. Run-level `inventory` includes
current registry reads, DNCP module coverage and Fabric freshness/errors.
Comparison is advisory, not an output of the material-neutral extraction
protocol. The product-library graph is incomplete; missing inventories and
unmatched candidates never establish novelty.

Persisted envelopes add `scan_id`, `scanned_at`, registered configuration and
`reviews`. Review events record item ID, action, human note and timestamp.
The four dispositions are exactly:

1. maps to existing capability
2. trusted solution to adopt
3. extend/customize/integrate
4. new knowledge/idea

`defer` and `reject` are review actions, not additional dispositions.
Choosing "trusted solution to adopt" records a human judgment only: it does not
adopt anything. Review events never change an item's provisional status.

## First repository implementation

Only explicitly registered local Git repositories may be scanned. Registering
does not read their tree or start a scan. Scans resolve a requested revision to a
commit, inventory its tree, and read blobs without checkout, hooks, fetches,
submodule traversal, code execution or working-tree reads. The registered
revision is the default; an explicit scan may choose another committed revision.
Dirty and untracked working-tree material is deliberately outside coverage.

The bounded standard-library extractors cover public top-level Python symbols,
JSON package manifests (`package.json`, `composer.json`), requirements lines and
Markdown headings. Python imports/private symbols, other manifest fields,
unheaded Markdown and unsupported files are recorded as residue. Markdown
headings are topics, not inferred architecture decisions. TOML and other
language formats are not parsed in this slice. Syft, SCIP, Repomix and LLM calls
are not required or invoked; no dependencies or GPL tools are added.

Default exclusions cover generated/cache/vendor directories and common
credential-bearing files. Registered path globs add exclusions. Git symlinks
and submodules are never dereferenced. A scan inventories at most 4 MiB of Git
tree output (larger trees fail explicitly), reads at most 200 files, 256 KiB per
file and 8 MiB total, and emits at most 1,000 items. Remaining material is
identified in coverage. Malformed/unsupported/secret-pattern content is visible
as errors/gaps, never a success-shaped empty extraction.

Extracted summaries are capped at 240 characters and recognized credential
patterns are redacted using Fabric's existing helper. Files containing
recognized credentials are excluded from content extraction. This is **not**
complete secret detection. Names, headings and dependency declarations may be
sensitive; register only material authorized for local review.

All persistence stays in `DEVNET_DATA_DIR` outside Git repositories and the
configured source roots. SQLite is local, unencrypted and accessible to the
same OS user; DNCP does not upload it. No full blob/source copies are retained.
There is no automatic retention deletion: the operator owns this runtime data.
Extraction order, evidence, IDs and frequency counts are deterministic for a
fixed commit/configuration; timestamps, review history and changing inventory
evidence are separate observation metadata.
