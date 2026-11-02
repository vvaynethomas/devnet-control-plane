# Explicit conversation-library consumer (DNCP-015 first slice)

DNCP can read an **explicitly selected, closed** PRJ-0006 local evidence library.
This is a CLI/adapter compatibility slice, not Fabric indexing, a Conversations UI
migration, or a handoff implementation. Existing chat surfaces are unchanged and
do not implicitly read this library. DNCP does not own collection or persistence.

## Verified boundary

The implementation targets producer
[`2673a87a2bef8c6055ed63ee5200aa1cde96ab37`](https://github.com/vvaynethomas/product-incubator/commit/2673a87a2bef8c6055ed63ee5200aa1cde96ab37),
inspected on 2026-11-02 after merged export/import and digest-scoped deletion:

- [`model.py`](https://github.com/vvaynethomas/product-incubator/blob/2673a87a2bef8c6055ed63ee5200aa1cde96ab37/projects/ai-conversation-hub/conversation_hub/model.py)
  defines the portable version-1 normalized record.
- [`library.py`](https://github.com/vvaynethomas/product-incubator/blob/2673a87a2bef8c6055ed63ee5200aa1cde96ab37/projects/ai-conversation-hub/conversation_hub/library.py)
  uses SQLite application ID `0x41434831`, user version `1`, and the `exports`,
  `revisions`, and `observations` tables.
- [The producer contract](https://github.com/vvaynethomas/product-incubator/blob/2673a87a2bef8c6055ed63ee5200aa1cde96ab37/projects/ai-conversation-hub/README.md#model-and-persistence-contract-version-1)
  describes identity, provenance, uncertainty, retained revisions and locators.
  DEC-0016 and ART-0008/0009/0010 remain draft evidence, not product acceptance or
  an approved long-term consumer API.

Phone-home's bounded repository check identified existing DNCP conversation,
Fabric and handoff modules. Reuse here extends the existing CLI without invoking
their collectors, creating another parser/store, or adopting a new dependency.
No sibling-checkout import or producer runtime invocation is needed.

## Explicit local use

Use authorized synthetic data first. Producer libraries belong outside Git in a
private, non-synced local directory. Close the producer before reading.

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

The output includes `source_freshness: "unknown"`: neither import timestamps nor
original-source availability/freshness are established by this producer model.
Conversation update timestamps are not collection timestamps. A missing original
export is not treated as missing library evidence; its bytes remain producer-owned.
There is deliberately no guessed time-to-live or automatic "latest" selection.

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
| `invalid_request` | Malformed expected SHA-256. |
| `unavailable` | Selected file missing, unreadable, corrupt, or query budget exceeded. No database is created. |
| `schema_incompatible` | Unsupported application/schema/record shape, inconsistent observation identity/provenance, or missing revision/export reference. No migration attempted. |
| `stale_snapshot` | Observations no longer match the caller's prior snapshot. |
| `library_busy` | WAL mode, journal/sidecar, or unsupported journaling; close/checkpoint using the producer. |
| `library_changed` | File identity, size or timestamps changed during the read; retry with producer closed. |
| `limit_exceeded` | Library over 32 MiB, more than 256 observations, any record over 256 KiB UTF-8, or total normalized JSON over 4 MiB. No truncation. |

SQLite opens with `mode=ro&immutable=1`, `query_only`, and trusted schema disabled.
Immutable mode prevents sidecar creation but does not support concurrent writers:
only quiescent default rollback-journal libraries are supported. WAL header flags
and sidecars are refused before opening; file state and sidecars are rechecked
afterward. These checks are conservative diagnostics, **not a synchronization or
adversarial race guarantee**. The producer's default journaling matches this
slice; DNCP never checkpoints, repairs, changes permissions, or writes its library.
SQLite VM execution is capped at one million steps.

## Validation and remaining work

`python -m unittest discover -s tests -p test_conversation_library.py -v` uses only
temporary synthetic libraries matching the producer's DDL. It covers preserved
branches/unknowns/locators/revisions, deletion and stale snapshots, unavailable
and incompatible input, exact byte/count limits, no source changes/sidecars,
and blocked collection, service construction, network and subprocess calls.

On 2026-11-02, a separate local compatibility probe used the pinned producer
modules and its authored CST, ChatGPT and Antigravity fixtures to create four
observations (two CST, one ChatGPT, one Antigravity). All normalized records
round-tripped exactly, consumer reads left database bytes unchanged and created
no sidecars, and the producer's digest-scoped deletion invalidated the prior
consumer snapshot. An isolated wheel install also ran the new CLI successfully
from an unrelated directory. No private histories or actual upstream exporters
were used. These are compatibility checks, not real-export acceptance.

Fabric/Conversations/Handoff wiring, an approved longer-term consumer contract,
real-history authorization and acceptance, cross-source identity reconciliation,
and source-freshness evidence remain open. No watcher, sync, background scan,
automatic handoff, transmission, producer change, or complete DNCP-015 acceptance
is delivered by this slice.
