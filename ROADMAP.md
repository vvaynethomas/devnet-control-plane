# DNCP Roadmap

**Status audit: 2026-11-01**, against `2c501ce` and freshly fetched `origin/main` (no divergence before this documentation change). The latest repository commit is dated 2026-11-01; that is not evidence that upstream development stopped. Release dates, acceptance, and any publication outside GitHub are unknown. No Git tags or GitHub Releases were listed at audit time.

## v0.1.0 — Foundational Nervous System (Declared Baseline; Acceptance Unverified)
- Standalone Python package (`devnet-control-plane`) declaring no required external runtime dependencies. Distribution is blocked: the declared CLI `control_plane.cli:main` and installed registry are missing.
- 6-Pillar Loopback Web Workbench implementation on `http://127.0.0.1:8780/`; end-to-end acceptance remains outstanding.
- Portfolio scanning across repositories discovered in `GitHub-Repos` (count depends on the local network, not a fixed 22).
- Cross-repo backlog aggregation with PAT-0001 deterministic router.
- SQLite FTS5 search across Factory entities & conversation transcripts.
- Request-time chat discovery (Antigravity, VS Code Copilot, and Copilot CLI); raw-text external import drawer and heuristic token estimates. No background sync or imported-chat Fabric indexing yet.
- Granular clipboard button implementation (Turn Pair, Prompt, Reply, Code-only); Full Handoff Packet compilation currently supports Antigravity only. Clipboard/feedback acceptance is unverified.
- Composable InteractionFrame compiler & benchmark evaluation runner.

Before declaring v0.1.0 delivered, resolve DNCP-001 packaging/CLI blockers and collect the acceptance evidence listed in [BACKLOG.md](BACKLOG.md).

## v0.2.0 — Universal Ingestion Deck & Zero-Touch AI Gateway (Planned; Next Target)
- **Network phone-home first (DNCP-014):** shared CLI/API/MCP/UI library check and
  provisional local report intake. Current discovery consumes one incubator's
  records/registries plus bounded local Python modules, not a graph of released
  product libraries. The Priority 1 ladder is network
  reuse/customization, an explicit external component check, an existing-product
  extension, then a justified standalone product. No live external research,
  canonical writes, or dispatch; human choice and unknowns remain visible.
- **Historical universal collection target, now transferring to PRJ-0006 ACH-004:**
  the following remains producer scope, not new DNCP collection work:
  - ChatGPT export bundles (`conversations.json`, `.zip`).
  - Google Gemini Chat exports (Google Takeout, web markdown/JSON).
  - Microsoft 365 Copilot (Enterprise transcripts, Purview compliance logs, clipboard dumps).
  - Claude & Perplexity web exports.
- **Historical watcher target, transferring to PRJ-0006 ACH-005:** narrow local
  refresh after the intake/adapter contract; no watcher is delivered in DNCP.
- **DNCP-015 consumer proposal:** consume the standalone product's local
  normalized conversation/provenance contract, not duplicate its collectors.
- **Zero-Touch Local AI Gateway:** OpenAI-compatible loopback proxy (`http://localhost:8781/v1/chat/completions`) routing Gemini API, Anthropic, Perplexity, and OpenAI calls with automated stream logging and token counting.

## v0.3.0 — The Metabolizer & Epistemic Context Mesh (Planned)
- **The Epistemic Matrix ("Who Knows What"):** Visual UI grid mapping agents (Antigravity, Copilot, ChatGPT, Gemini, Human) against projects and architectural decisions, flagging context drift in real time.
- **The Shared Blackboard HUD:** Live bulletin board tracking confirmed decisions, active roadblocks, file locks, and cross-repo dependencies.
- **The "Metabolizer" Agent:** Historical background synthesis/24h briefing target
  remains unimplemented. The user-approved provisional first digester is instead
  opt-in, explicit, bounded and deterministic repository evidence/residue for
  human review; no scheduled scan or mandatory agent reporting.
- **Model Context Protocol (MCP) Server:** Native `devnet-context-server` allowing any MCP-compliant agent (Claude Code, Antigravity, Cursor) to pull situational context without human copy-pasting.

DNCP-011 (local model bridge) and DNCP-012 (ALM consumer exchange) remain unscheduled P3 backlog items; the configurable outbound completion client is only partial evidence for DNCP-011. Versions above are scope targets, not release commitments or acceptance records.

## Unreleased Advisory Integration (DNCP-013)

The existing Capability Discovery pillar now surfaces infrastructure-decision, coordination/recoverability, and capability-routing guidance from canonical incubator records through an explicit tag contract. The Decision Aid shows operator-entered constraints, questions, unranked alternatives, statuses and provenance without dispatch, provider selection, cost/readiness scores, or a second knowledge store. This is a bounded advisory slice awaiting acceptance, not delivery of the planned epistemic matrix, Metabolizer, MCP server, or ALM exchange.

## Next-Round Ownership and Acceptance

**Library architecture clarification:** the network library is a graph of product
libraries; each product ships its own library with its release. DNCP has its own
product library and must surface/attend that graph, rather than centralize every
product's library in the incubator. Existing incubator-owned records keep their
canonical contract. Present Fabric record refs and local AST scans are not
implemented product-node discovery or release-library federation.

The graph-wide follow-on requires product-library/release contracts (including
DNCP), node/edge discovery, namespaced product/release identity, cross-node
search/provenance, per-node freshness/version/availability, and owner-directed
discovery review. This is outstanding scope, not a delivery claim, a new
prioritization, or DNCP-015 chat integration. No graph synchronization/federation
is built as part of this clarification; see [BACKLOG.md](BACKLOG.md) for coverage
evidence and proposed acceptance boundaries.

DNCP-014 is first and now has portable implementation coverage. It restores
callable CLI/installed-registry prerequisites, adds only a bounded stdio
capability/intake MCP adapter, and preserves the Decision Aid and docs audit.
It does not close DNCP-001 publication/provenance gates or DNCP-010's live-state
scope. Search coverage/freshness and provisional intake remain explicit;
matching text is not proof of operational readiness.

The incubator's provisional **PRJ-0006** draft lives in
`projects/ai-conversation-hub/` (README, BACKLOG, ROADMAP); its working title and
priorities remain undecided. SRC-0020 records operator direction. DNCP-005
collection points to ACH-004 intake; DNCP-004 collection points to ACH-005
watcher; ACH-003 owns local adapters. The reported reuse direction is
`copilot-session-tools` (MIT/PyPI) for Copilot CLI/VS Code, with
ChatGPT/Antigravity adapters on top. Verification and implementation belong to
that producer, not this branch.

Sequence: phone-home, producer ChatGPT intake slice, producer narrow watcher,
then DNCP consumer integration against an available local contract. Each later
item runs phone-home before design/code. Preserve existing DNCP P1/dependency
history, leave new ACH priorities unassigned, and treat duplicate-queue
reconciliation as open owner work: these documents do not synchronize queues
or create another canonical backlog.

Parsing is currently duplicated in `fabric.py`, `handoff.py`, and
`conversations.py`; no migration/refactor occurs here. Universal export parsing,
imported-chat Fabric integration, all-harness handoffs, and continuous refresh
are still gaps. The digital asset catalog handles file/cloud metadata, not chats;
the producer should inspect its collector envelopes, safe hashing/identity, and
placeholder/link guards before reimplementing. See [BACKLOG.md](BACKLOG.md) for
concrete paths, ownership handoff, and acceptance gates.

## First Repository Digester (Provisional Direction; Bounded Implementation)

A repository is the first material type DNCP can digest into useful static
evidence and review proposals. `devnet digest register` stores local opt-in only;
a later explicit `scan` pins committed HEAD or `--revision` and reads recognized bounded docs/
manifests/config/Python AST material. Dirty files, source/Git writes, repository
execution, dependency installation, LLM calls, external transmission, and
scheduled reporting are outside the slice.

Output includes material/reference/revision, extractor/version/time, evidence
links/digests/paths/lines, material items, errors/exclusions/limits, and bounded
untargeted/repeated residue. Counts are frequency, not independent corroboration.
The material-neutral extraction protocol is separate from repository registration
and comparison; one `digest` CLI exposes the coherent implementation.
An already-built matching-root canonical-only Fabric cache supplies provisional candidate matches, not a
complete product-library graph, novelty proof, or trust judgment. Human review
may reuse/customize/extend/integrate, propose knowledge, defer or reject; the
destination product retains ownership and the incubator is optional.

No auto-adoption, code copying, dispatch, canonical creation/promotion, queue
mutation or phone-home reporting occurs. This composes existing DNCP observation/
AST/Fabric pieces, not a new product, other digester, concierge or router.
Specialist SBOM/symbol extractors require demonstrated gaps before adoption.
See [README.md](README.md) for commands/limits,
[the shared contract](docs/digester-contract.md) for extraction boundaries, and
[BACKLOG.md](BACKLOG.md) for bounded acceptance evidence; prior background/
blackboard and graph-wide delivery gates remain open.
