# ALM lifecycle ledger consumer (DNCP-012)

DNCP can validate and list an explicitly selected ALM lifecycle ledger. This is a
read-only consumer boundary: nothing is imported into DNCP, copied into an agent's
configuration, installed, promoted or executed, and no component is reported as trusted.

```powershell
python -m pip install ".[alm]"
devnet alm inspect --manifest <ledger.json>
devnet alm inspect --manifest <ledger.json> --root <checkout> --kind skill
devnet alm inspect --manifest <ledger.json> --id <component-id>
```

## What the "ALM registry" is

Agent Lifecycle has no registry service. `alm-lifecycle-core` validates a ledger file:
an envelope with `registry: "alm-lifecycle"`, `schema_version: 1`, `owner: "PRJ-0005"`
and sealed entries. Each entry has an ID, kind, explicit numeric version, provenance
citations and a `revision` that is the SHA-256 of its canonical body. Component kinds
(agent, prompt, skill, tool and others) carry their files with content and digest, pinned
dependencies and an origin. Other kinds record configurations, evaluations, proposals,
reviews, releases and deployments. No ledger is inferred from a checkout; the operator
names the file.

## Pinned validator

The optional `alm` extra pins `alm-lifecycle-core` 0.2.0a1 at commit
`a5aac7abbdf8a82d6fd89cc485d00e5d4961c66f`
([release v0.2.0a1](https://github.com/vvaynethomas/agent-lifecycle/releases/tag/v0.2.0a1);
published wheel SHA-256
`c041ca3ceb33eb947f4e3ca7f60751d02a867a04306e5c0cf284eca500fe83a2`). The core has no
runtime dependencies. DNCP loads it the same way as Material Core: it checks the installed
version and PEP 610 source commit, captures the distribution-owned sources and executes
those bytes under a private namespace. DNCP contains no second validator.

Only the authenticated Git install path is supported in this slice. The offline
wheel-evidence installer used for Material Core has not been extended to this package, so
a bare local wheel install is refused. PEP 610 is source provenance, not post-install
byte-integrity verification; the wheel digest above is producer evidence that the running
consumer does not enforce.

Without the extra, or with another version or source, the command fails with
`capability_missing` or `capability_unverified` (status 503) and install guidance. The
public base package is unchanged and still has no runtime dependencies.

## Behaviour

- **Explicit input.** `--manifest` is required. The file must be a regular file of at
  most 16 MiB. There is no discovery, registration, cache or background read.
- **Validation.** `LifecycleRegistry` checks the envelope, every record's fields and
  revision hash, embedded file content against its digest, references, version reuse and
  dependency cycles. With `--root`, each recorded file digest is also compared with the
  file under that directory, so drift is a validation failure naming the relative path.
- **Output.** Contract, validator identity, the ledger's SHA-256 and counts by kind; then
  each selected component's ID, kind, version, revision, provenance citations, origin,
  pinned dependencies, file paths with digests, and the configurations and releases that
  use it. **File content is never printed.** Releases list the core's readiness result
  and blockers. `trusted` and `live_deployment_verified` are always false.
- **Filters.** `--kind` and `--id` narrow the component list; an unknown kind or ID is
  `not_found` (404).
- **Errors.** `unavailable` for a missing, oversized or unreadable file or root;
  `ledger_invalid` with the core's message, which names record IDs, fields and relative
  paths. Errors are JSON on stderr with a `code` and never echo file content or the
  supplied path.

## Registered ledgers in the reuse check

```powershell
devnet alm register --manifest <ledger.json> --root <checkout>
devnet alm list
devnet alm disable --manifest <ledger.json>
```

`register` validates the ledger, then stores its absolute path, the optional checkout
root, an enabled flag and a timestamp in `alm_ledgers.json` in the DNCP data directory
(at most 20 ledgers). It copies nothing from the ledger. Re-registering a path replaces
its entry; `disable` keeps the entry but stops reading it.

`phone_home_check` (CLI, Python and MCP) then adds `alm_ledger_components`: components
of every enabled ledger whose ID, kind, origin, file paths or **file content** match the
query, ranked like other capabilities (ID matches weigh more). Content is matched but
never returned. Each item has its ID, kind, version, revision, a reference
`alm:<id>@<version>`, origin, pinned dependencies, the ledger's digest and path, and
`trusted: false`.

- **No cache.** Ledgers are read and validated on every check. A ledger that fails
  (missing, invalid, or the extra absent) is reported in `warnings` and
  `coverage.alm_ledgers` and does not hide the others.
- **Drift.** With a registered root, each recorded file digest is compared with the file
  under it and reported per file as `match`, `changed` or `missing`
  (`not_compared` without a root). Unlike `inspect --root`, drift here does not fail the
  ledger; the component is still listed with `workspace_drift: true` and a warning.
- **Not ladder evidence.** These components are listed apart from the decision ladder
  and do not change its recommendation or `stopped_at`, because nothing in a ledger has
  been evaluated or approved. A human reads them alongside the ladder.
- With nothing registered the check is unchanged apart from an empty list and zero
  counts, and the `alm` extra is not needed.

Comparison with the incubator's cockpit skill and prompt registries was considered and
left out: on 2026-11-10 the two existing candidate ledgers shared no file, by content
or by meaningful name, with the 14 cockpit entries, so there was nothing real to compare.

## Trust boundary

A valid ledger is structurally consistent, nothing more. Evaluations, reviews and
deployments in it are recorded assertions, not authenticated attestations, observed
behavior or live state, and reviewer identity is not verified. This command grants no
authority and changes no canonical record. The ledger and the optional root are read
only; nothing is written anywhere.

## Evidence and remaining work

`python -m unittest tests.test_alm_exchange -v` covers a synthetic ledger built with the
pinned core: listing without content, filters, root drift, tampered, dangling, malformed
and oversized ledgers, the missing or unverified core refusal and CLI output, plus
registration, per-file drift, a failing ledger beside a readable one, content matching
without content output, and the reuse check leaving the decision ladder unchanged. Tests that
need the core skip when the extra is absent.

On 2026-11-10 two existing candidate ledgers (Conversation Hub and its producer, 14
entries each: 6 agents, 6 skills, 2 prompts) validated, and one validated with `--root`
against its own checkout with no drift. Neither holds a release, so the readiness output
is **not exercised** by a real or synthetic ledger. The isolated install matrix
(`test_consumer_extras.py`) was not extended to this extra.

The operator's own data directory has no registered ledger; the reuse check was
exercised against the two candidate ledgers through a temporary data directory only.

Still open under DNCP-012: the workbench Capabilities tab does not show ledger
components; citing component revisions from `handoff_prepare`; the offline wheel path. Copying skill or prompt files
into DNCP or agent configuration is deliberately not planned. Priority (P3), ownership and
acceptance are unchanged.
