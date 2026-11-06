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
