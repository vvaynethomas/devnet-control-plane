# Conversation Hub consumer integration

DNCP uses the standalone Conversation Hub's explicit-source readers for the
existing Antigravity, VS Code Copilot, Copilot CLI, and legacy imported-chat
conversation surfaces, and for Antigravity and Copilot CLI Fabric indexing.
Antigravity conversation discovery, Fabric indexing, and handoff now request
the producer's explicit directory-first selection policy to preserve DNCP's
existing caps. DNCP can also read an **explicitly selected** PRJ-0006 local evidence
library. This is an unaccepted development integration. The selected Hub
dependency is a private, untrusted prerelease; its
verified component bytes do not imply behavioral qualification or product
acceptance.

## Verified boundary

The implementation targets producer
[`11c362c621727a331a1ecf9ffee40220d8a6d373`](https://github.com/vvaynethomas/product-incubator/commit/11c362c621727a331a1ecf9ffee40220d8a6d373),
which merged PRJ-0006's explicit local reader contract:

- [`model.py`](https://github.com/vvaynethomas/product-incubator/blob/11c362c621727a331a1ecf9ffee40220d8a6d373/projects/ai-conversation-hub/conversation_hub/model.py)
  defines the portable version-1 normalized record.
- [`library.py`](https://github.com/vvaynethomas/product-incubator/blob/11c362c621727a331a1ecf9ffee40220d8a6d373/projects/ai-conversation-hub/conversation_hub/library.py)
  uses SQLite application ID `0x41434831`, user version `1`, and the `exports`,
  `revisions`, and `observations` tables. `read_snapshot` validates identifiers in
  one read-only SQLite transaction with a bounded busy timeout; it supports
  consistent WAL snapshots and reports locked/busy failures rather than empty data.
- Every normalized record has a UTC `provenance.observed_at` timestamp. This is
  when the export was imported, not when the source conversation was last checked.
- [The producer contract](https://github.com/vvaynethomas/product-incubator/blob/11c362c621727a331a1ecf9ffee40220d8a6d373/projects/ai-conversation-hub/README.md#model-and-persistence-contract-version-1)
  says consumers reject missing, unknown or future application/schema identifiers
  and never migrate. The producer's import path refuses unmarked databases without
  initialization. DEC-0016 and ART-0008/0009/0010 remain draft evidence, not product
  acceptance or an approved long-term UI contract.

The standalone `conversation-hub` package is pinned as an **optional dependency**
to the exact v0.1.6 prerelease source commit
[`ea8d608b00aa1900132b2d2f33d90561143fa471`](https://github.com/vvaynethomas/conversation-hub/commit/ea8d608b00aa1900132b2d2f33d90561143fa471).
The published wheel
`conversation_hub-0.1.6-py3-none-any.whl` was independently checked at
SHA-256 `bb0da00debc8c13b166030b14eb26e3100afff65318ca1dd7a3b68dbc8448c16`.
It remains a private, untrusted prerelease: its release metadata explicitly says
`trusted: false`, `ready_for_human_release_decision: false`, and evaluation is
not complete. Install this private extra with Python 3.12+ and repository access:

```powershell
python -m pip install '.[conversation-hub]'
```

This extra remains independent of `material`: install both explicitly with
`python -m pip install '.[material,conversation-hub]'`. Both the standard
setuptools and custom release wheels preserve the Hub commit and Python marker;
neither private repository is required for a public base install.

The extra is marker-gated to Python >=3.12 because that is the producer's declared
minimum. DNCP's base install remains dependency-free and supports Python >=3.10;
unrelated features continue working on 3.10/3.11. The
`conversation-library` command requires the extra and returns `hub_unavailable`
with installation guidance if it is absent; it does not silently use a DNCP
fallback reader.

When installed, the consumer opens the library through the exact pinned
commit's `conversation_hub.library.read_snapshot(Path)` API, which provides a
validated read-only connection inside a transaction. DNCP keeps additional
bounded record and schema checks for its output contract. At runtime, DNCP
verifies the installed distribution version, VCS source URL, and full commit
from its `direct_url.json`, then loads all required Hub modules directly from
files owned by that checked distribution under a private module namespace. It
does not resolve `conversation_hub` through `sys.path` or reuse an already-loaded
module; absent or incompatible distribution files fail explicitly. PEP 610 metadata records
installation provenance, not byte integrity: it does not prove that installed
files were not modified after installation. The wheel digest above is recorded
as independent release verification only; DNCP does not download the wheel or
enforce that digest at runtime. The output's `library_reader` field
reports the Hub version and recorded commit used. The same checked distribution
supplies explicit-root Antigravity, VS Code Copilot, Copilot CLI, legacy imported
chat, library-read, and redacted-view APIs. DNCP passes the roots it already
selects; it adds no new home-directory discovery, watcher, background scan, or
network transmission. Existing DNCP roots and per-surface limits are retained where defined: the
Conversations aggregator selects at most 25 Antigravity directories, 500 VS Code
files, and 500 CLI event files; Fabric selects at most 20 Antigravity directories
and 25 CLI files; handoff selects at most 20 Antigravity directories. The current
Hub Antigravity reader supports `selection_policy="directory-first"`: DNCP passes
this option for each migrated Antigravity surface, so the producer sorts session
directories by directory mtime, applies the existing cap, and then checks
transcript availability. The v0.1.4 diagnostic correction remains in v0.1.6
without changing directory-first selection behavior. DNCP explicitly requests
directory-first rather than relying on the reader's default policy. VS Code and
CLI omissions and producer limitations are included in diagnostics or logs.
Legacy imported-chat SQLite reads are read-only.
Root readers explicitly opt into `malformed_sources="skip-file"`: malformed
selected files are diagnosed and valid siblings retained, without refilling
selected slots. Source path/I/O and file/root/event/nesting resource failures
remain fatal. Handoff's direct parser uses `read_antigravity_transcript` with
`malformed_lines="skip-line"` to read exactly the requested existing file,
including off-layout or beyond-cap selections. Standard paths retain their
session-directory identity; off-layout selection uses a deterministic URI hash
as the caller-supplied identifier. Skipped line diagnostics preserve raw-byte
provenance; recognized-field and resource errors remain explicit. Local root and
exact-file readers opt into `utf8_errors="replace"`, preserving legacy replacement
decoding with safe replacement counts and exact raw-byte provenance. CLI opts
into `timestamp_policy="legacy-string"` for the first truthy timestamp's
`str(value)[:19]` display, without claiming temporal validity.
CLI manager and Fabric request producer physical-line windows of 100 and 120
respectively. Blank/unsupported lines consume slots; JSON beyond the window is
not parsed or exposed, but full-byte/nonblank-event resource checks still apply.
Fabric uses `conversation_view(content_limit=800, strip_content=True)` to bound
original stripped content before redaction. Complete tokens crossing that source
boundary are fully replaced; no ordinary post-boundary source text is included.
The replacement label may make the displayed result longer than 800 characters.
These are transient read-only views, never persisted into the producer library.
Local-source responses keep filesystem paths in `source_path` and retain Hub's
original file URI separately as `source_uri`. CLI Fabric indexing and conversation
presentation preserve the redacted producer message order, including unassigned
preludes and attached tool/unknown messages. Search includes that visible content
without relabeling it as user or assistant dialogue.
Local token totals include redacted tool/system/unknown content in a separate
`est_unclassified_tokens` estimate, not an invented input/output split. Known
user/assistant roles outside dialogue turns remain classifiable. CLI sessions
use their first qualifying redacted message as the title regardless of role,
from permitted display messages only, rather than fabricating a dialogue
turn or exposing a later excluded prompt through metadata. Manager CLI eligibility
uses only string `message`/`content` values from producer-parsed source records;
Fabric retains the producer's additional text/dictionary support. Manager CLI
estimates use original qualifying string lengths, without returning raw strings,
over the selected source window including messages beyond the ten displayed
snippets; title, dialogue and search remain display-bounded.
Imported-chat and no-Hub
token-estimation behavior is unchanged.
Conversation copy controls carry JSON-encoded text in HTML-escaped data
attributes, never interpolate transcript content into JavaScript. Literal
backslashes, template expressions, quotes and line breaks remain clipboard
data. Public base compatibility is checked on actual Python 3.10/3.11 without
the optional Hub; Python 3.10's SQLite lock diagnostics use an exact-message
compatibility check where error-name attributes are unavailable.
Without the optional dependency, existing DNCP readers remain as a logged/visible
compatibility path. An installed but
mismatched package fails explicitly and does not fall back.

The separate `conversation-library` CLI requires the optional extra and only
opens its caller-supplied library path. It does not invoke local source readers,
collectors, or network access.

## Explicit local use

Use authorized synthetic data first. Producer libraries belong outside Git in a
private, non-synced local directory.

```powershell
devnet conversation-library --library 'C:\Private\ConversationHub\library.sqlite'
devnet conversation-library --library 'C:\Private\ConversationHub\library.sqlite' --expected-snapshot '<previous-snapshot-sha256>'
```

Success prints JSON including **conversation bodies and unredacted source
metadata** to stdout. This differs from the producer's count-only import output.
Do not redirect it into Git, shared logs, cloud storage, or a handoff without
separate authorization. The command itself transmits nothing and retains no
DNCP copy, cache, index or intake. Global DNCP root/data defaults are not read or
created by this command. Export URIs are literal evidence and are never followed;
neither original files nor personal harness directories are opened.

`read_conversation_library(path, expected_snapshot=None)` returns all observations,
including multiple revisions and copied export locators, without choosing a
current revision, flattening branches, pairing turns, or merging identities.
Producer IDs are opaque: derivation differs between source adapters. Message
positions may have gaps from structural graph nodes; content, source order,
native event/branch references, source record, limitations, and provenance remain
unchanged. No token estimates, redaction, trust or approval are inferred.

## Diagnostics and bounds

The output includes `observation_time: "per_observation"` and retains each
`provenance.observed_at` as the producer-recorded UTC import time. It separately
reports `source_freshness: "unknown"`: an import timestamp does not establish that
the original conversation/export remains available or current. Conversation
update timestamps are not collection timestamps. A missing original export is
not treated as missing library evidence; its bytes remain producer-owned. There
is deliberately no guessed time-to-live or automatic "latest" selection.

`snapshot_sha256` covers canonical JSON of **all normalized observations**, ordered
by conversation ID, revision, export digest and URI. It is not a raw-library or
raw-export integrity attestation. JSON whitespace and row insertion order do not
change it. `--expected-snapshot` refuses changed observation sets (including
producer deletions) with `stale_snapshot`, rather than returning cached or partial
data. Without the option, `snapshot_check` is `not_requested`, not "fresh".
Empty exports with no observations are outside this snapshot scope.

Errors exit nonzero, emit a structured `code`, `error` and numeric `status` on
stderr, and emit no partial stdout or imported content:

| Code | Meaning |
| :--- | :--- |
| `hub_unavailable` | Optional private Conversation Hub extra is not installed. Install `devnet-control-plane[conversation-hub]` with Python 3.12+ and repository access. No local reader fallback is used. |
| `hub_incompatible` | Installed extra is not v0.1.6 at the configured full commit or lacks a required library/source/view API. Reinstall the optional extra. |
| `invalid_request` | Malformed expected SHA-256. |
| `unavailable` | Selected file missing, unreadable, corrupt, or query budget exceeded. No database is created. |
| `schema_incompatible` | Unmarked, unsupported application/schema/record shape, inconsistent observation identity/provenance, or missing revision/export reference. No migration attempted. |
| `stale_snapshot` | Observations no longer match the caller's prior snapshot. |
| `library_busy` | SQLite reports a busy/locked read after the one-second timeout. Retry after current access ends. WAL is supported; no empty-result fallback. |
| `limit_exceeded` | Library over 32 MiB, more than 256 observations, any record over 256 KiB UTF-8, or total normalized JSON over 4 MiB. No truncation. |

SQLite opens with `mode=ro`, `query_only`, trusted schema disabled, a one-second
busy timeout, and one explicit read transaction spanning contract/schema checks
and all observations. This provides a single SQLite snapshot; a concurrent WAL
writer may commit without changing the rows visible to the reader. A busy/locked
error is reported as `library_busy`, not hidden as an empty collection. Unmarked,
unknown and future application/schema identifiers are rejected before row use;
the pinned Hub reader and consumer never initialize or migrate the producer
database. SQLite VM execution is capped at one million steps. Do not copy the
library while it is being written; the producer has no live-library backup
protocol. DNCP never checkpoints, repairs, changes permissions, or writes its
library. This is snapshot consistency, not a backup or recovery protocol.

## Fabric index over the library

`devnet fabric index-hub --library <explicit-path>` copies redacted message text
from a version-1 library into the rebuildable Fabric cache so it can be searched
with FTS5. It exists because the bounded reader above refuses real libraries
(32 MiB / 256 observations / 256 KiB per record) by design.

```powershell
devnet fabric index-hub --library 'C:\Private\ConversationHub\library.sqlite'
```

- **Read path.** `control_plane/hub_index.py` opens the library itself with
  `mode=ro`, `query_only`, trusted schema disabled, a one-second busy timeout and
  one read transaction. It checks the application ID, user version and the three
  table shapes, then streams messages with SQLite `json_each`, so a large record
  is never loaded whole. It does not import or require the optional Hub package
  and works on Python 3.10+. This is a second DNCP read path beside the pinned
  Hub `read_snapshot`; both enforce the same version-1 identifiers.
- **What is stored.** Per revision: opaque conversation ID and revision, platform,
  title (or a flagged title derived from the first message), timestamps and
  message count. Per chunk of about 8,000 characters: redacted `role: content`
  text and the first and last message positions. Raw exports, `source_record`,
  export URIs and provenance are not copied. The cache therefore **contains
  personal conversation text**; it lives in the DNCP data directory, which is
  ignored by Git, and must stay out of synced or shared locations.
- **Incremental.** Tables `hub_revisions`, `hub_chunks_fts` and `hub_metadata`
  sit beside the Fabric tables and are not dropped by `FabricIndex.rebuild`. A
  run indexes revisions the cache lacks and removes revisions the library no
  longer holds; each revision commits on its own, so an interrupted run resumes.
  There is no watcher or background run: the cache is as fresh as the last
  explicit command, reported as `conversation_hub.indexed_at` in Fabric freshness.
- **Search.** With `include_hub=True`, which only the workbench Fabric tab and
  its JSON endpoint pass, `FabricIndex.search` returns Hub hits as `kind: "conversation"`
  with `id: "hub:<conversation_id>"`, the matching `revision`, `revision_count`,
  `message_offset` and a `conversation-hub://` locator. Every revision is
  indexed; results show the best-ranked chunk per conversation and never label a
  revision current. Hub and Fabric hits are interleaved by FTS5 bm25 score, which
  is lexical relevance only. Entity-ID mentions in Hub text are not linked into
  the provenance graph. Phone-home checks, capability discovery and repository
  digests do not opt in, so indexed conversation text does not enter their
  output or stored proposals.
- **Output and errors.** The command prints counts and timings only. Failures
  use the codes above (`unavailable`, `schema_incompatible`, `library_busy`) and
  never echo paths or content. A record with another `schema_version`, an
  unknown role, a non-increasing position or mismatched identity stops the run;
  revisions committed before it remain.

Message extraction is isolated in `chunk_messages`, which accepts any ordered
`(position, role, content)` stream, so a shared extractor can replace it later
without changing storage or search.

On 2026-11-09 the operator's own library (4.16 GB, 461 revisions of 253
conversations, largest record 32.7 MB) was indexed into a temporary cache: 14.7 s
for the first run, 0.01 s for an unchanged second run, 2,138 chunks, 13.1 million
characters and a 22.6 MB cache. Three sample queries returned in 65 to 105 ms.
Only these aggregates were recorded. This is one machine and one library, not
cross-platform or product acceptance.

## Validation and remaining work

`python -m unittest tests.test_hub_index -v` covers the Fabric index with
temporary synthetic libraries only: search and message offsets, incremental
re-runs and removals, revision collapsing, duplicate observations, a 2 MiB record,
redaction, survival across `rebuild`, incompatible/unmarked/future libraries, a
busy library, an unmodified source file and count-only CLI output.


`python -m unittest tests.test_conversation_hub_adapter tests.test_conversation_library -v`
uses temporary synthetic source files/databases and library fixtures only. It
covers optional-package fallback, exact-distribution loading, source diagnostics,
Fabric/handoff projections, UI diagnostic escaping, stale/unavailable/schema
errors, bounded reads, and concurrent WAL snapshot behavior. The same tests pass
without the optional package (with its package-integration cases skipped) and
with exact commit `ea8d608b00aa1900132b2d2f33d90561143fa471` installed into a
temporary target directory. The downloaded release wheel hash matched the
published digest; the integration test exercises the VCS-commit install so its
PEP 610 metadata matches the pin. No real
conversation directories or histories were read. Hub-backed validation ran on
Python 3.14.2 (57 tests passed). No-extra validation and compilation ran on actual
Python 3.10.22 and 3.11.18 (38 tests passed, 19 optional-package cases skipped
on each). Cross-platform real-history acceptance is not established.
Fresh base-package installations in isolated Python 3.10/3.11 environments also
passed installed UI/handoff imports with Hub absent, using only the public PyPI
build-tool index and no private-package installation.

On 2026-11-02, a cross-repository compatibility probe used the actual producer
modules at `11c362c621727a331a1ecf9ffee40220d8a6d373` plus its authored synthetic
CST, ChatGPT and Antigravity fixtures. The three adapters created four records;
the producer's `read_snapshot` output, consumer output, and serialized model
records matched exactly, including UTC `observed_at` values. Separately, the
consumer tests verify a stable WAL snapshot while a concurrent synthetic writer
commits, and verify a redacted busy error under an exclusive rollback-journal
lock. No producer schema implementation is copied into DNCP, and no private or
live exports were read.

The earlier adapter probe against the pre-PR-39 producer revision is superseded
for this contract check; its installed-wheel check remains separate packaging
evidence, not validation of the new observation timestamp or snapshot API.

## Remaining release and acceptance gates

The v0.1.6 prerelease source APIs provide explicit-root Antigravity, VS Code Copilot,
Copilot CLI, legacy imported-chat reads, conversation reads, and redacted views.
Synthetic tests exercise all four producer readers and the migrated consumer
surfaces without opening a real history. Remaining boundaries are:

| Area | Remaining gate |
| :--- | :--- |
| Dependency pin | v0.1.6 is pinned to the exact source commit; the prerelease tag is mutable, private, and explicitly untrusted/not ready for a human release decision. Promotion and product qualification remain open. Python >=3.12 remains a Hub-extra requirement; DNCP no-extra tests and compilation have passed on actual 3.10/3.11. The wheel digest is not checked at runtime. |
| Producer diagnostics | DNCP uses v0.1.6's explicit directory-first Antigravity policy and malformed-source isolation. Coverage, physical-window/decoding diagnostics, selected-slot/no-refill semantics and resource failures are covered with synthetic fixtures. |
| Raw-text import / writes | DNCP's existing user-initiated raw-text import and its legacy SQLite persistence are not migrated: v0.1.6 offers a read-only legacy database adapter, not an equivalent user import, write, or deletion lifecycle. Existing behavior remains DNCP-owned. |
| Fabric / UI semantics | Fabric indexing and the existing UI remain DNCP responsibilities. Token estimates remain DNCP heuristics, not Hub metrics. Producer limits and unversioned-source limitations are exposed through diagnostics; this is not complete history or identity reconciliation. |
| Handoff | Discovery uses Hub's directory-first projection; parsing uses its bounded exact-file API, preserving off-layout and beyond-cap explicit selection. DNCP retains handoff Markdown and selection UI. No automatic handoff or transmission is added. |
| Malformed-source compatibility | v0.1.6 opt-in per-file failure policy retains valid selected siblings without cap refill or bound evasion. Strict producer defaults remain unchanged. |
| Direct transcript compatibility | Hub and no-Hub paths parse exactly the supplied existing file and skip malformed JSON/object lines. Hub retains stricter recognized-field/resource checks with explicit errors; an incompatible installed Hub always fails closed. |
| CLI physical-window compatibility | Fabric uses 120 physical lines, 12 qualifying excerpts, original-source 800-character limits and boundary-safe redaction. Manager/UI/search uses 100 physical lines and the first 10 qualifying string message/content values, retaining truthful roles/order; estimates count all qualifying original string lengths in that window. Producer owns physical selection and raw evidence; no consumer parser or normalized-index reconstruction is used. |
| UTF-8 replacement compatibility | Local root/exact-file reads explicitly request producer replacement decoding, including bytes beyond CLI windows. Raw-byte/hash evidence, replacement diagnostics and global resource bounds remain intact; producer defaults remain strict. |
| CLI timestamp display | Explicit legacy-string projection preserves first truthy JSON timestamp display; numeric/object values are not silently interpreted as dates. |
| Product acceptance | Real-history authorization, cross-source identity reconciliation, source-freshness evidence, a stable tagged consumer contract, and owner acceptance remain open. Component/prompt release tracking belongs in ALM's release gate. |

These are release and behavior gates, not a request to add scanning, syncing, or
handoff features to the Hub without separate approval. Component/prompt release
tracking belongs in ALM's release gate, not this consumer. An approved longer-term
consumer contract, continuing private package access, real-history authorization
and acceptance, cross-source identity reconciliation, and source-freshness
evidence remain open. No watcher, background scan, automatic handoff, transmission,
producer change, or complete DNCP-015 acceptance is delivered by this development
integration.
