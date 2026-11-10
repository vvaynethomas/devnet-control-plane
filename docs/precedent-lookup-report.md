# Precedent lookup milestone report

**Branch:** `vvaynethomas-precedent-lookup`  
**Base:** `origin/main` at `afc4d9c` (the handoff merge); worktree was clean before changes.

## Delivered

- Added direct, non-persistent `find_precedents(query, records, context=None, limit=10)` and `inspect_precedent(implementation_id, records)` APIs in `control_plane/precedents.py`.
- Exposed the same bounded behavior through optional stdio MCP tools `devnet_find_precedents` and `devnet_inspect_precedent`.
- Added the adapter schema, ownership/trust boundaries, invocation examples and retrieval limits in [the usage guide](precedent-lookup.md).
- No source files, registries, databases, Fabric indexes, or product-owned records are read or written. Inputs are explicitly supplied and treated as unverified. No commit, push, or PR was created.

## Synthetic query check

| Need query | Expected top candidate | Observed |
|---|---|---|
| Avoid partial network write for invalid-UTF-8 streaming CSV | `PAT-9001`, `commit-a` | `PAT-9001`, `commit-a` (lexical relevance 11); scoped mixed/success evidence, with explicit partial-write warning |
| Reject duplicate JSON keys in manifests | `PAT-9002`, `commit-json` | `PAT-9002`, `commit-json` |
| Prevent private user data crossing accounts; enforce tenant isolation | Synthetic failed shared-cache transfer in `example-product-b` | Failed transfer ranked first; successful account-scoped control from `example-product-a` also remained visible |
| Browser canvas image zoom | No match | No result |

This fixed synthetic set returned the expected top candidate for 3/3 positive cases and no result for the unrelated negative case. The privacy example tests product-name-independent retrieval and surfaces both a success control and failed transfer, but does not state or verify an actual incident cause. It measures fixture retrieval only—not general relevance, security effectiveness, operational success, or product endorsement. `commit-b` remained a separate revision with an unknown outcome rather than inheriting `commit-a`'s failure.

## Validation

- `test_precedents.py`: 8 tests pass, including the synthetic multi-account privacy need.
- `test_phone_home_mcp.py`: 3 tests pass, including calls to both new tools over MCP stdio.
- `test_phone_home.py`: 10 tests pass.
- `git diff --check`: clean.

Semantic/hybrid retrieval, real owner-record mapping, authentication, durable feedback, and verified applicability remain unimplemented.

## Follow-up requirement

When planning private multi-user web data, retrieve analogous cross-account
isolation controls and failed transfer/adaptation evidence across product
boundaries. Regression design should include both a negative cross-account
access check and a positive same-account control. A retrieved precedent is a
lead for inspection, not proof of root cause, security, or approval. No actual
Personal Tracker or DAC source/evidence was inspected or modified for this
follow-up; incident-specific assertions remain unverified pending their owners.
