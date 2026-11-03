# Conversation Hub consumer integration

DNCP uses the standalone Conversation Hub's explicit-source readers for the
existing VS Code Copilot, Copilot CLI, and legacy imported-chat conversation
surfaces, and for Copilot CLI Fabric indexing. Antigravity remains on DNCP's
legacy reader until the producer can preserve its existing directory-first cap
semantics. DNCP can also read an **explicitly selected** PRJ-0006 local evidence
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
to the immutable v0.1.2 prerelease commit
[`381644edec4c948375bc6f24b695bbba7b699e7a`](https://github.com/vvaynethomas/conversation-hub/commit/381644edec4c948375bc6f24b695bbba7b699e7a).
The published wheel
`conversation_hub-0.1.2-py3-none-any.whl` was independently checked at
SHA-256 `537dd2fc8f792742d64fd6377b3fa706af8fb2d8f2af7b491dbe5a82a30237c1`.
It remains a private, untrusted prerelease: its release metadata explicitly says
`trusted: false`, `ready_for_human_release_decision: false`, and evaluation is
not complete. Install this private extra with Python 3.12+ and repository access:

```powershell
python -m pip install '.[conversation-hub]'
```

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
files were not modified after installation. The output's `library_reader` field
reports the Hub version and recorded commit used. The same checked distribution
supplies explicit-root Antigravity, VS Code Copilot, Copilot CLI, legacy imported
chat, library-read, and redacted-view APIs. DNCP passes the roots it already
selects; it adds no new home-directory discovery, watcher, background scan, or
network transmission. Existing DNCP roots and per-surface limits are retained where defined: the
Conversations aggregator selects at most 25 Antigravity directories, 500 VS Code
files, and 500 CLI event files; Fabric selects at most 20 Antigravity directories
and 25 CLI files; handoff selects at most 20 Antigravity directories. The current
Hub Antigravity reader caps supported transcript files after filtering; that
differs from DNCP's historical directory-first cap, so those surfaces retain the
legacy Antigravity reader and report/log the compatibility limitation. VS Code
and CLI omissions and producer limitations are included in diagnostics or logs.
Legacy imported-chat SQLite reads are read-only.
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
| `hub_incompatible` | Installed extra is not v0.1.2 at the configured full commit or lacks a required library/source/view API. Reinstall the optional extra. |
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

`python -m unittest tests.test_conversation_hub_adapter tests.test_conversation_library -v`
uses temporary synthetic source files/databases and library fixtures only. It
covers optional-package fallback, exact-distribution loading, source diagnostics,
Fabric/handoff projections, UI diagnostic escaping, stale/unavailable/schema
errors, bounded reads, and concurrent WAL snapshot behavior. The same tests pass
without the optional package (with its package-integration cases skipped) and
with exact commit `381644edec4c948375bc6f24b695bbba7b699e7a` installed into a
temporary target directory. The downloaded release wheel hash matched the
published digest; the integration test exercises the VCS-commit install so its
PEP 610 metadata matches the pin. No real
conversation directories or histories were read. Validation ran on Python 3.14;
Python 3.10 and 3.11 were not available, so those versions remain unverified.

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

The v0.1.2 prerelease source APIs provide explicit-root Antigravity, VS Code Copilot,
Copilot CLI, legacy imported-chat reads, conversation reads, and redacted views.
Synthetic tests exercise all four producer readers and the migrated consumer
surfaces without opening a real history. Remaining boundaries are:

| Area | Remaining gate |
| :--- | :--- |
| Dependency pin | v0.1.2 is an immutable prerelease pin, but is private and explicitly untrusted/not ready for a human release decision; promotion and product qualification remain open. Python >=3.12 remains a Hub-extra requirement; DNCP base Python >=3.10 support remains optional and unverified on 3.10/3.11 in this environment. |
| Antigravity selection | Add a producer API that accepts DNCP's already-selected session directories/transcript paths, or otherwise preserves DNCP's directory-first cap semantics. Until then conversation, Fabric, and handoff deliberately retain DNCP's parser for this source. |
| Raw-text import / writes | DNCP's existing user-initiated raw-text import and its legacy SQLite persistence are not migrated: v0.1.2 offers a read-only legacy database adapter, not an equivalent user import, write, or deletion lifecycle. Existing behavior remains DNCP-owned. |
| Fabric / UI semantics | Fabric indexing and the existing UI remain DNCP responsibilities. Token estimates remain DNCP heuristics, not Hub metrics. Producer limits and unversioned-source limitations are exposed through diagnostics; this is not complete history or identity reconciliation. |
| Handoff | Antigravity selection and parsing remain DNCP-owned until the producer supplies a directory-first compatibility API. DNCP retains its existing handoff Markdown format and selection UI. No automatic handoff or transmission is added. |
| Product acceptance | Real-history authorization, cross-source identity reconciliation, source-freshness evidence, a stable tagged consumer contract, and owner acceptance remain open. Component/prompt release tracking belongs in ALM's release gate. |

These are release and behavior gates, not a request to add scanning, syncing, or
handoff features to the Hub without separate approval. No watcher, background
scan, automatic handoff, transmission, producer change, or complete DNCP-015
acceptance is delivered by this development integration.
