# Bounded precedent lookup (development integration)

DNCP exposes an optional, direct-callable lexical adapter for finding and
inspecting explicitly supplied precedent records. It does not use or rebuild
Fabric: `FabricIndex.search()` may initialize an index that harvests local
conversations, which is not an acceptable side effect for this lookup.

The adapter distinguishes:

1. A technique or pattern (`technique.id`, title, and summary).
2. One implementation at an exact source locator and revision.
3. Append-only evidence events scoped by need, runtime, input, and constraints.

Outcomes are `success`, `failure`, `mixed`, `inconclusive`, or `unknown`.
Corrections and disputes are additional events referencing an earlier
observation in the same source record; inspection retains the original event
and shows its correction/dispute history. The last correction in the supplied
record order determines the effective projection; every correction remains in
the inspected event history. Revisions are separate variants.
Unknown outcomes never count as success. Duplicate event content is shown but
not counted twice; independence between distinct reports cannot be verified.

## Ownership and limits

The `records` argument is a bounded **adapter payload**, not a new canonical
record schema, registry, feedback store, or approval workflow. A caller maps
authorized, owner-maintained source records into this shape. This checkout does
not contain or assert the approval of the draft DEC-0015/SRC-0033 contract.
Canonical records and implementation source remain owned by their products.

For private multi-user web data, planning should search for prior cross-account
isolation controls and negative evidence about failed transfers/adaptations
across products—not only records that share the product name. A retrieved
precedent is a prompt to inspect its implementation revision, conditions, and
regression evidence; retrieval is not proof of a security fix, root cause, or
approval. Regression plans should include a negative cross-account access test
and a positive control showing that an account can still access its own data.

`record_ref`, implementation `source_ref`, and evidence `source_ref` are opaque
locators. DNCP does not open them, fetch URLs, read repositories, execute
supplied code, write feedback, or mutate owner records. Inputs are limited to
50 records, 200 total evidence events, and 64 KiB of JSON. Recognized credential
patterns are rejected, but detection is incomplete; pass only material the
caller is authorized to disclose.

Retrieval uses deterministic lexical term overlap and explains matched terms,
fields, and relevance score. An avoidance query prioritizes relevant negative
or disputed evidence; it does not rank implementations by success. Scope
comparisons are exact labels only, not a judgment of applicability. Relevance,
scope completeness, source integrity, and outcome remain separate; no
similarity or count establishes independent corroboration, trust, readiness, or
endorsement. Outcome summaries list observed labels and evidence entries, not a
success rate or independent-support count. There is no semantic embedding/hybrid
retrieval. That would need a representative, owner-approved benchmark showing a
measurable gap over this small fixed-query baseline before adoption.

## Direct Python API

Call `find_precedents(query, records, context=None, limit=10)` and
`inspect_precedent(implementation_id, records)` from
`control_plane.precedents`. The same source records must be supplied to each
call; no global or persistent index is created. For example:

```python
from control_plane.precedents import find_precedents, inspect_precedent

# `owner_records` is an explicit mapping of records the caller is allowed to use.
found = find_precedents(
    "avoid partial write for malformed CSV",
    owner_records,
    context={
        "runtime": "Python 3.12",
        "input": "malformed CSV",
        "constraints": "network writes disabled",
    },
)
history = inspect_precedent("csv-reader", owner_records)
```

Each adapter record has exactly these top-level fields:

```json
{
  "record_id": "FND-9001",
  "record_revision": "sha256:owner-record-revision",
  "record_ref": "product/knowledge/FND-9001.md",
  "technique": {
    "id": "PAT-9001",
    "title": "Bounded streaming CSV ingestion",
    "summary": "Process delimited input incrementally."
  },
  "implementation": {
    "id": "csv-reader",
    "source_ref": "product/src/csv.py",
    "revision": "immutable-source-revision"
  },
  "observations": [
    {
      "event_id": "run-001",
      "event_type": "observation",
      "target_id": "",
      "need": "streaming CSV ingestion",
      "outcome": "failure",
      "scope": {
        "runtime": "Python 3.12",
        "input": "invalid UTF-8 CSV",
        "constraints": "network writes prohibited"
      },
      "summary": "Malformed UTF-8 caused a partial network write.",
      "source_ref": "product/reports/run-001.json",
      "revision": "immutable-report-revision"
    }
  ]
}
```

`event_type` is `observation`, `correction`, or `dispute`. A correction carries
the replacement need/outcome/scope/summary and points to its earlier
`target_id`; it never erases that observation. A dispute points to an earlier
observation, uses `unknown` as its outcome, and keeps its rationale in
`summary`. Revision values may be `null` when unknown.

## Optional MCP tools

The existing optional `devnet mcp` stdio server provides
`devnet_find_precedents` and `devnet_inspect_precedent`. Pass the same bounded
`records` array to each tool; `devnet_find_precedents` additionally accepts
`query`, optional `context`, and `limit`. These tools are local retrieval only,
not new write endpoints, authenticated delivery, or a required runtime
intermediary. Install the existing MCP extra to run the server:

```powershell
python -m pip install "devnet-control-plane[mcp]"
devnet mcp
```

## Synthetic validation

`tests/test_precedents.py` uses only synthetic owner-record-shaped fixtures:
success on one revision, a failure later corrected to mixed on that same
revision, an unknown outcome on another revision, an unrelated JSON failure,
and duplicate/disputed evidence. Its fixed need queries assert the expected
top candidate for two relevant needs and no result for an unrelated need; this
is a retrieval check, not an operational success rate or evidence of any real
product outcome. `tests/test_phone_home_mcp.py` exercises both tools over the
existing stdio server when the optional MCP dependency is installed.

The fixed set also includes a purely synthetic private-data isolation query:
problem wording (without a product name) retrieves a successful account-scoped
control from one example product and a failed shared-cache transfer from another.
The failed transfer is surfaced first for an avoidance query, but the result
does not establish any real incident cause or security approval.
