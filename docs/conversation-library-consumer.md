# Explicit conversation-library consumer (DNCP-015 first slice)

DNCP can read an **explicitly selected** PRJ-0006 local evidence library.
This is a CLI/adapter compatibility slice, not Fabric indexing, a Conversations UI
migration, or a handoff implementation. Existing chat surfaces are unchanged and
do not implicitly read this library. DNCP does not own collection or persistence.

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

The standalone `conversation-hub` package is pinned as an **optional** dependency
at verified v0.1.1 commit
[`2e00f9861ea60b083aaf7d0be779bcef1e23d7c2`](https://github.com/vvaynethomas/conversation-hub/commit/2e00f9861ea60b083aaf7d0be779bcef1e23d7c2).
The earlier v0.1.0 candidate is not used. Install this private extra with Python
3.12+ and repository access:

```powershell
python -m pip install '.[conversation-hub]'
```

The extra is marker-gated to Python >=3.12 because that is the producer's declared
minimum. DNCP's base install remains dependency-free and supports Python >=3.10;
unrelated features continue working on 3.10/3.11. The
`conversation-library` command requires the extra and returns `hub_unavailable`
with installation guidance if it is absent; it does not silently use a DNCP
fallback reader.

When installed, the consumer opens the library through the pinned package's
`conversation_hub.library.read_snapshot(Path)` API, which provides a validated
read-only connection inside a transaction. DNCP keeps additional bounded record
and schema checks for its output contract. At runtime, DNCP verifies the installed
distribution version, VCS source URL, and full commit from its `direct_url.json`;
it refuses an unpinned or incompatible installation. The output's `library_reader`
field reports the Hub version and exact commit used.
Phone-home's bounded repository check identified existing DNCP conversation,
Fabric and handoff modules. The CLI does not invoke their collectors, create
another parser/store, or follow export URIs.

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
| `hub_incompatible` | Installed extra is not v0.1.1 at the pinned full commit or lacks `read_snapshot`. Reinstall the pinned extra. |
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

## Validation and remaining work

`python -m unittest discover -s tests -p test_conversation_library.py -v` uses only
temporary synthetic libraries matching the producer's DDL. It covers preserved
branches/unknowns/locators/revisions, deletion and stale snapshots, unavailable,
incompatible/unmarked input, exact byte/count limits, redacted busy diagnostics,
one consistent WAL read during a concurrent writer, and blocked collection,
service construction, network and subprocess calls. The snapshot-reader seam is
synthetically tested against the published `read_snapshot(Path)` context-manager
shape. The no-package path is tested to return actionable `hub_unavailable`
instead of silently falling back. The producer package itself must be installed
to run this test suite's integration path through the real pinned implementation.

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

## Producer interfaces needed for further migration

The published export-library API is not yet a behavior-equivalent replacement
for DNCP's active local conversation features. Before migrating those surfaces,
the Hub needs explicit APIs and synthetic compatibility tests for:

| DNCP surface | Minimum producer behavior needed before replacing it |
| :--- | :--- |
| Live local scanners | An explicit, user-triggered source adapter contract for supported local roots, with bounded discovery, permission/error diagnostics, stable source identity, source observation times, and no new implicit/background scans. Each source needs its own opt-in and tests proving no paths outside the selection are accessed. |
| Raw-text import | A user-invoked import API for pasted text that preserves the exact submitted text, caller-provided source label, and provenance/limitations; defines retention/deletion; and does not infer a parser or claim source freshness. |
| Fabric indexing | A stable read/query API over normalized records plus documented index lifecycle and filtering semantics. It must preserve branch structure, revisions, source evidence, and unknown fields and must not silently collapse records into an alternate DNCP-owned store. |
| Conversations UI | Paginated/filterable query APIs and explicit import/delete operations sufficient for existing source filters, conversation details, raw-text import, and source/provenance display. Token metrics need defined estimator/version semantics or must remain explicitly unavailable. |
| Handoff | Explicit user-selected conversation/message retrieval and a serialization/rendering contract that preserves Antigravity transcript ordering, branch/tool events, and provenance, with tests for the existing handoff output. Selection must not trigger collection or transmit automatically. |

These are interface/behavior gates, not a request to add scanning, syncing, or
handoff features to the Hub without separate approval. Component/prompt release
tracking belongs in ALM's release gate, not this consumer.

An approved longer-term consumer contract, corrected immutable standalone-hub
commit and package access, real-history authorization and acceptance, cross-source
identity reconciliation, and source-freshness evidence remain open. No watcher,
sync, background scan, automatic handoff, transmission, producer change, or
complete DNCP-015 acceptance is delivered by this slice.
