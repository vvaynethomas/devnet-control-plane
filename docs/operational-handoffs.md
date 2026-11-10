# Local operational handoffs

This development slice adds durable packets and correlated reports to the
existing phone-home SQLite inbox, not a second store, product registry or
acceptance workflow. It requires no incubator records, conversation import,
ALM release, model provider or delivery service. It does not change the existing
Antigravity transcript-to-Markdown handoff compiler.

`PhoneHome` exposes `handoff_submit(payload)`, `handoff_get(handoff_id)`,
`handoff_result(payload)` and `handoff_list(recipient="", scope="", limit=20,
offset=0)`. These Python operations work without MCP or UI. The existing
`devnet mcp` local stdio server exposes the same four tool names. There is no
new handoff CLI command, HTTP write endpoint, UI or background agent.
The existing generic inbox list/get/export can read these stored records.

## Packets and results

The submit operation accepts exactly:

| Field | Meaning |
|---|---|
| `handoff_id` | Caller-stable, globally unique within this inbox; 1-100 ASCII letters/digits/`.`/`_`/`:`/`-`, beginning with a letter/digit. Also serves as the retry key. |
| `mode` | `request` or `information`. Information never appears in pending requests and requires no acknowledgement/result. |
| `sender`, `recipient` | Explicit caller-supplied labels, each at most 200 characters. Not authenticated identities, discovery targets or authority. |
| `scope` | Up to 20 labels, each at most 200 characters, grouping repositories/products/tasks without changing ownership or requiring registration. |
| `context_snapshot` | Nonempty, at most 20,000 characters; a bounded snapshot, **not complete effective runtime context**. |
| `requested_action` | Required only for requests, nonempty and at most 2,000 characters; forbidden on information. Stored as data, never executed. |
| `blockers` | Up to 20 nonempty strings, each at most 1,000 characters; may be empty. |
| `source_refs` | Up to 20 objects with exactly `ref` (nonempty, at most 2,000 characters) and `revision` (nonempty, at most 200 characters, or `null` for unpinned/unknown). References may name informal material, conversations, source commits, package digests or reports. |

Result operations require exactly `result_id`, `handoff_id`, `responder`,
`outcome`, `summary`, `blockers` and `source_refs`. IDs have the same limits as
packet IDs. The responder must match the packet's declared recipient; this is
correlation validation, **not authentication**. Summary has the same limit as
context; references/blockers have the same shapes as above.
Outcome is `blocked`, `preview` or `completed`; blocked requires at least one
blocker. Results for informational packets are refused.

The server stores schema version 1 and adds an inbox ID (`HANDOFF-` or `RESULT-`
plus the stable ID), submission time, content SHA-256, unknown source freshness
and a non-authority notice. Retrying an identical stable ID returns its original
receipt, including timestamp. Reusing an ID with different content returns 409,
including trying to correlate an existing result ID to another packet.
Packet and result IDs occupy separate namespaces. Explicit submission of a new
result ID appends a report; it never edits the original packet or earlier reports.
The latest inserted result is current, not the latest source date. Retrying an
older result does not make it current.

Get returns the immutable `packet`, latest `result` (or null), and a
caller-reported `state`: `received` before any result, otherwise the outcome.
**Received is not accepted; reported completion is not verified completion.**
List returns only requests whose latest outcome is not `completed`, so blocked
and preview requests remain pending. A later blocked report reopens that view;
there is no approval or enforced lifecycle state machine. Recipient and scope
filters are exact and case-sensitive, not substring or wildcard matches. Page
size is 1-50 (default 20); offset is 0-2147483647. Results and packets are also
retained for generic inbox export, even when absent from the pending view.

## Preparing a packet with retrieved references

`PhoneHome.handoff_prepare(payload)` and the MCP tool `handoff_prepare` are
read-only. They store nothing, submit nothing, build no cache and open no
reference. The caller reviews the returned draft, adds `handoff_id`, `mode`,
`sender` and `recipient`, and submits it with `handoff_submit`.

Input (all optional, but at least one of `query`, `requested_action` or `scope`):
`query` (at most 2,000 characters; replaces the derived search text), `scope`,
`requested_action`, `context_snapshot`, `source_refs` (kept first in the draft),
`include_conversation_hub` (default true) and `limit` (1-10 per source, default 5).
Search terms are the distinct words of `query`, or of `requested_action` plus
`scope`, without common stop words, capped at 24.

Four local sources are searched:

| Source | What matches | Reference written to the draft |
|---|---|---|
| Past handoffs | The newest 500 packets in this inbox that share an exact scope label or match a search term anywhere in the packet or its reported results (see ranked search below); ordered by shared scope, relevance, then recency. Each match reports its latest caller-reported state and a 200-character preview of the requested action, never context or result text. | `handoff:<handoff_id>`, revision `sha256:<content digest>` |
| Fabric records | Lexical matches among knowledge and registry records in an already built Fabric cache. Ambient local session transcripts are excluded. | the record ID, revision `null` |
| ALM ledgers | Components of explicitly registered ALM ledgers (see [the ALM consumer note](alm-ledger-consumer.md)) whose ID, kind, origin or file paths contain a search term. File content is not matched for citations. Each match reports kind, version, drift against its registered checkout and `trusted: false`. | `alm:<id>@<version>`, revision pinned to the record's hash |
| Conversation Hub | Lexical matches in the explicitly indexed library (see [the consumer contract](conversation-library-consumer.md#fabric-index-over-the-library)). | `conversation-hub://<id>/<revision>#message=<n>`, revision pinned |

**The draft carries references only.** No conversation text, snippet or record
body is copied into it, because a submitted packet is retained in the
unencrypted, exportable inbox. A Conversation Hub match reports platform,
dates, counts and the message offset; its title is included only when the
source supplied one, never when it was derived from message text. A recipient
reads a referenced conversation through Conversation Hub with its own access.

The draft's `source_refs` hold the caller's references first, then matches
taken alternately from the four sources up to the 20-entry packet limit;
`matches` lists every match with `rank` and `in_draft`, and
`references_omitted` counts those that did not fit. `coverage` says which
sources were searched: an unbuilt Fabric cache or an unindexed library is
reported there, not treated as "no precedent". Matches are lexical relevance,
not applicability, trust or endorsement, and referenced material remains
untrusted historical data.

## Ranked search over stored handoffs

`PhoneHome.handoff_search(query="", scope="", recipient="", state="", limit=10)`
and the MCP tool `handoff_search` are read-only and return past handoffs in
**any** state, including completed ones that `handoff_list` hides. This makes
earlier exchanges, and how they ended, retrievable as precedent.

With a query, packets are ranked by FTS5 bm25 over the requested action
(weighted highest), scope labels, context snapshot, blockers and every reported
result's summary and blockers, with Porter stemming; any query term may match.
Without a query they are listed newest first. `scope` and `recipient` are exact,
case-sensitive filters and `state` is one of `received`, `blocked`, `preview`
or `completed` (the latest caller-reported outcome). Each entry carries the
`handoff:<id>` reference and content digest, mode, sender, recipient, scope,
state, timestamps, result count, a 200-character preview of the requested
action, the latest blockers when blocked, and, for a query, a short bracketed
snippet of the matching text. Use `handoff_get` for the full packet.

The workbench Queues tab shows the same search (query and state filter, 20
entries) and can display a prepared draft for a query. Both are read-only, with
JSON at `/api/handoffs?q=&state=&scope=&recipient=`, `/api/handoffs?id=` and
`/api/handoff-prepare?q=`. Submitting still goes through `handoff_submit`. The
panel was tested by rendering against synthetic packets and checked in a browser on 2026-11-10 against synthetic data (and, for status codes and counts only, the operator's real data); the embedded browser denied clipboard writes, so copy buttons were verified up to the request and the error toast, not the clipboard.

Nothing is cached or indexed on disk: each call loads the newest 500 packets
and ranks them in a temporary in-memory table, so results cannot be stale and
no second copy of inbox text exists. `scanned` and `truncated` report when
older packets were left out. Stored handoffs are deliberately **not** added to
the Fabric cache or to `devnet_search_fabric`. Ranking is lexical relevance
only; a reported outcome is not verified completion.

## Trust and storage boundaries

No reference is fetched, opened or resolved; a declared revision/digest is
preserved but not verified, and freshness remains **unknown**. Link an existing
report instead of copying it into every exchange. Provisional observations do
not become decisions, components, policies or releases. Canonical code/config/
policy changes still belong in their owning products.

The same local stdio/OS-user trust boundary as phone-home applies: no network MCP
listener, per-recipient authorization, isolated mailbox or new credentials are
added. Any client with access to this inbox can read and write its records.
Caller labels do not grant rights or establish that a recipient actually acted.
Received text, including imperative or malicious text, remains untrusted data.
Consumers must apply their own permissions and review before any action.

Payloads are capped at 64 KiB of UTF-8 JSON, reject unknown fields, unsupported
control characters, invalid values and recognized credential patterns, and never
truncate content. Snapshots and literal refs retain whitespace. Validation errors
do not echo supplied content; missing IDs return 404, conflicts 409 and oversize
payloads 413, using `PhoneHomeError` and MCP error results rather than empty success.
Known-pattern detection is incomplete: callers must not submit secrets or
unauthorized private material. The existing local SQLite storage is **not
encrypted**, and full snapshots are retained in it. Use private, authorized
runtime storage outside Git, preferably synthetic data first. No canonical
repository writes, execution, dispatch, automatic promotion or transmission
are introduced by these operations.

This thin DNCP adapter does not settle long-term ownership of a reusable handoff
capability. Products may use underlying APIs/capabilities directly; DNCP and the
incubator are not mandatory runtime intermediaries. Global discovery, autonomous
delivery, ALM package qualification/release, live cross-agent state and product
library federation remain outside this slice.

## Honest offline loop

The synthetic contract fixtures in `tests\test_operational_handoffs.py` submit
an ALM-style package/compatibility report reference with an explicitly fake
digest to `synthetic-delivery-preview`, then append a blocked preview result:
no real recipient service or qualified package was supplied. Retrieve by
`synthetic-alm-compatibility-1`; the packet's references and correlated result
survive reopening `PhoneHome`.

The test loop makes no claims about ALM's pending worktree, merged releases,
package readiness, deployment, approval or a functioning delivery product.
`tests\test_phone_home_mcp.py` exercises these operations through real SDK
stdio negotiation, including stopping/restarting the server and retrieving the
same durable result. Service tests cover concurrent retries, conflicts,
literal provenance, pending/informational separation, pagination and invalid/
credential-bearing data, without reading real conversations or source refs.
