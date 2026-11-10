# DNCP Backlog

Authoritative product delivery queue for the **Development Network Control Plane (DNCP)** system node.

**Evidence audit: 2026-11-01**, against commit `2c501ce` (also `origin/main` after fetch). Statuses describe this checkout, not release publication or operator acceptance. `Awaiting acceptance` means implementation is present but acceptance is unverified; `Open (partial)` means some criteria are implemented, not that the whole task is done.

| Task ID | Scope and Acceptance Criteria | Depends On | Priority | Status |
| :--- | :--- | :--- | :--- | :--- |
| DNCP-001 | Standalone repository graduation and dependency-bounded package distribution. | None | P1 | Open (partial; public base remains dependency-free; CLI/registry restored; material extra privately released and commit-pinned; DNCP publication and operator acceptance remain open) |
| DNCP-002 | 6-Pillar Loopback Web Workbench GUI (Portfolio, Queues, Fabric, Conversations, Capabilities, Interaction Lab). | DNCP-001 | P1 | Awaiting acceptance (implementation and packaged launch present; full operator acceptance outstanding) |
| DNCP-003 | Multi-harness Conversation Hub: auto-harvest Antigravity and VS Code Copilot, tokenomics tracking, and 1-click granular copy controls. | DNCP-002 | P1 | Open (partial; request-time scans and estimated tokens present) |
| DNCP-004 | Historical collection scope: Live Background Watcher for Conversation Fabric. Future collection delivery moves to PRJ-0006 ACH-005; DNCP consumes its interface. | DNCP-003 | P1 | Transfer proposed (owner queue reconciliation open; watcher not implemented here) |
| DNCP-005 | Historical collection scope: Universal Ingestion Deck for ChatGPT, Gemini, M365 Copilot, Claude/Perplexity. Future collection delivery moves to PRJ-0006 ACH-004; DNCP consumes its interface. | DNCP-003 | P1 | Transfer proposed (raw-text paste remains here; owner queue reconciliation open) |
| DNCP-006 | Anti-Fatigue Granular Copy Controls: 1-click Handoff Packet, Code-Only Extractor, Turn Pair, and Prompt/Reply split buttons with toast confirmations. | DNCP-003 | P1 | Awaiting acceptance (anti-fatigue toast system, button pulse, and clipboard fallback implemented globally in ui.py; full operator acceptance outstanding) |
| DNCP-007 | Zero-Touch Local AI Gateway Proxy: loopback /v1/chat/completions proxy logging streaming tokens, prompts, and costs for Gemini API, Claude API, Perplexity, and OpenAI. | DNCP-004 | P2 | Open |
| DNCP-008 | Epistemic Matrix & Knowledge Drift Inspector: visual UI grid showing agent knowledge coverage across 22 repos, drift detection, and 1-click alignment briefs. | DNCP-005 | P2 | Open |
| DNCP-009 | The Metabolizer & Shared Blackboard: historical background synthesis/24h digest scope; approved provisional first repository digester is explicit opt-in and user-invoked, not scheduled synthesis or required reporting. | DNCP-008 | P2 | Open (partial; bounded deterministic repository evidence/residue and provisional cached comparison implemented; blackboard/background synthesis not implemented) |
| DNCP-010 | Model Context Protocol (MCP) Server: devnet-context-server exposing live cross-agent state, portfolio status, and handoff packets to any MCP-enabled tool. | DNCP-009 | P2 | Open (partial; local reuse/intake and durable operational handoff/result stdio tools implemented; no live cross-agent state, automatic delivery or Metabolizer server) |
| DNCP-011 | Native Local Model Bridge for Interaction Lab (Ollama / llama.cpp / vLLM localhost endpoint) for offline side-by-side frame benchmarks. | DNCP-002 | P3 | Open (partial; configurable OpenAI-compatible client present) |
| DNCP-012 | Automated ALM Agent Consumer Exchange: import versioned agent skills and prompts directly from the ALM product registry. | DNCP-001 | P3 | Open |
| DNCP-013 | Read-only Decision Aid in Capability Discovery: discover canonical topic-tagged incubator records, show constraints/questions/alternatives/status/provenance, preserve uncertainty, and perform no dispatch or provider selection. | DNCP-002 | P2 | Awaiting acceptance (unreleased integration; synthetic fixture and HTTP coverage) |
| DNCP-014 | Network phone-home front door: shared CLI, loopback API, optional official-SDK stdio MCP and existing UI; check available library/toolbox sources before building; append provisional intake with provenance/manual export and no canonical writes. Ordered ladder: network reuse/customization, external component check, existing-product extension, justified standalone only. Stop at evidence; unknown external check explicit; human final choice, no dispatch. Intended network library is a graph of released product-owned libraries; current coverage is one incubator plus bounded local Python modules, not graph-wide discovery. | DNCP-002 | P1 | Awaiting acceptance (bounded front-door implementation covered; graph-wide library coverage not implemented; first next-round gate) |
| DNCP-015 | Read PRJ-0006's local conversation/provenance contract without duplicating collection; eventual Fabric, Conversations and Handoff integration. Require schema/identity, stale/unavailable-source diagnostics and read-only acceptance. | DNCP-014, PRJ-0006 consumer contract | P1 | Open (partial; explicit-path read-only CLI consumer of pinned v1 contract and explicit incremental Fabric index over a v1 library with opt-in MCP search and a Conversations panel; Handoff integration, contract approval and owner acceptance remain open) |
| DNCP-016 | Network Deployment & Infrastructure Observer: read repository edge and persistence manifests (vercel.json, package.json, Supabase schema pointers) in Portfolio discovery to surface edge deployment topology, build readiness, and drift alongside Git status without triggering mutations or remote deploys. | DNCP-002, DNCP-013 | P2 | Open |

## Evidence and Remaining Acceptance Gates

**Operational handoff development slice (2026-11-04):** callable Python service
and four MCP stdio tools reuse the existing phone-home inbox for immutable
caller-ID packets and correlated reports, with pending request filters.
Informational packets need no acceptance. Synthetic service and real SDK
stdio restart tests cover the offline ALM-style report/blocked-preview loop,
idempotency/conflicts, provenance and validation. This is not a real delivery
service, verified completion, ALM release qualification, or complete DNCP-010
acceptance; no priorities/dependencies change.
See [the operational contract](docs/operational-handoffs.md).

The following table preserves the **baseline audit**. Subsequent phone-home, digester and
ownership changes are recorded below; baseline missing-CLI/registry statements
are historical evidence, not the current checkout state.

| Tasks | Repository evidence | Needed to finish |
| :--- | :--- | :--- |
| DNCP-001 | **Baseline audit (2026-11-01):** `pyproject.toml`, `control_plane/__init__.py`, and `release.py` declared 0.1.0 with no required runtime dependencies; both console scripts and the installed fallback registry were absent. | The baseline CLI/registry gaps have since been restored. Current DNCP pins the private material-core release at commit `108fe9f309005ac7593fd640fce54bc196262198`. DNCP publication, independent core license/ownership approval, and operator acceptance remain unverified. |
| DNCP-002 | `control_plane/ui.py` defines all six tabs and a loopback server. `tests/test_control_plane.py` covers rendering but relies on external Factory/network fixtures for most pillars. | Run with controlled Factory/network fixtures and demonstrate all six tabs/endpoints plus packaged launch. Current evidence supports provisional implementation, not full acceptance. |
| DNCP-003, DNCP-004 | `UnifiedConversationHub.get_all_conversations()` scans Antigravity, VS Code Copilot, and Copilot CLI on each request. Tokens are character-based estimates; some source/model metadata is heuristic. No filesystem watcher is present. | Validate supported transcript schemas, dialogue pairing and metadata, all-harness handoffs, and background updates without page reload/re-harvest. Do not equate request-time discovery with a daemon. |
| DNCP-005 | `import_external_chat()` persists raw text in SQLite; `/action/import-chat` accepts a text form. Hub search is in-memory substring filtering. `FabricIndex.rebuild()` does not ingest the imported-chat database. | Add and demonstrate platform export parsers, zip/file drop handling, format preview, metadata mapping, and imported-chat Fabric indexing. Ordinary SQLite storage is not encryption. |
| DNCP-006 | `render_conversations_tab()` has turn/prompt/reply/code buttons and temporary inline "Copied!" feedback. `compile_context_handoff()` discovers only Antigravity; unmatched imported/VS Code/CLI sessions return an error and the UI uses empty markdown. | Verify clipboard output and nonempty correct handoffs for every supported harness, including error behavior and the specified toast UX. Browser clipboard acceptance is unknown. |
| DNCP-007-DNCP-010, DNCP-012 | No inbound AI proxy, epistemic state/matrix, blackboard/synthesizer, MCP server, or ALM registry exchange implementation is present. The outbound Interaction Lab completion client is not an inbound gateway. | Implement and validate the stated criteria; design text is not delivery evidence. |
| DNCP-011 | `InteractionFrameEngine._try_live_llm()` accepts `OPENAI_BASE_URL` and `INTERACTION_LAB_MODEL`, but requires a nonempty `OPENAI_API_KEY` and falls back to a labeled deterministic preview on failure. | Demonstrate real offline completions against supported local runtimes, appropriate local authentication, and persisted model/mode evidence. A configured URL or deterministic preview alone does not prove a native bridge. |

No outstanding item was fully closed by this audit. DNCP-002 is provisionally implementation-complete only; priorities and dependencies remain unchanged. See [ROADMAP.md](ROADMAP.md) for planned release scope.

**Subsequent integration, separate from the audit:** DNCP-013 implements advisory surfacing only. `control_plane/decision_aid.py` reuses the canonical Fabric collector and exact topic tags; `tests/test_decision_aid.py` covers provisional/active/draft status, current-source reads, provenance, missing data/errors, escaping, and the read-only HTTP/UI surface. A 2026-11-01 read-only cross-repository check verified all three actual topic mappings, active findings and the draft routing pattern, resolved source chains, and Fabric/Capability UI/API behavior with temporary local runtime storage and unchanged producer-record hashes. Operator acceptance remains outstanding; this does not finish DNCP-008/DNCP-009/DNCP-012 or implement a routing optimizer. Generic queue discovery, P3 parser repair, hosting deployment, autonomous execution, and credentials remain outside this slice.

**Queue-consumer limitation:** `control_plane/queues.py` recognizes only P0-P2 in this five-column format, so DNCP-011/DNCP-012 P3 rows are misinterpreted by that parser. Preserve their P3 priorities here; verify a parser repair before relying on aggregated priority/dependency data for those rows.

## Next Round: Phone-Home First, Chat Collection Owned Elsewhere

**DNCP-014** implements the user-directed Priority 1 ladder consistently in CLI,
API, MCP and UI. Existing capability matches cite evidence and recommend human
review for customization, not verified readiness. External research is never
performed: the explicit unresolved external check cannot be replaced with guessed
candidates. Provisional `external_evidence` and literal `source_ref` allow a human/
agent to record component candidates with links without trusting/fetching them.
Registry products are candidate owners only; standalone recommendation requires
resolved earlier checks, an explained lack of a suitable existing owner,
independent network/outside value, and human ownership/maintenance approval.

### Product-Library Graph: Coverage and Outstanding Scope

The user clarified that the network library is a **graph of product libraries**:
each product releases its own library, and DNCP both has its own product library
and surfaces/attends the graph across product nodes. There is no centralized
canonical owner for every product's library. Incubator-owned records retain
their existing IDs/frontmatter/provenance contract and source of truth.

Current evidence supports only one-incubator knowledge consumption
(`fabric.py:collect_knowledge_entities`, `capabilities.py:discover_capabilities`),
incubator registry owner candidates (`phone_home.py:check`), and bounded local
Python scans including DNCP (`capabilities.py:scan_network_modules`). The shipped
DNCP code/InteractionFrame registry is not evidence of a versioned product-library
manifest or graph node. Record refs inside Fabric and local module owner/path
labels must not be presented as a resolved graph of released product libraries.

**Follow-on scope proposal, not implemented or assigned a new priority here:**
define product-owned library/release manifests, DNCP's own declared library,
node and edge discovery, product/release-namespaced identity, cross-node search/
provenance, per-node version/freshness/unavailability evidence, and destination
product-owner review for discovery intake. Agree ownership and contracts before
implementation. This is distinct from DNCP-015's chat-product consumer proposal;
it does not assign library ownership to the incubator or create a duplicate
canonical network library/backlog.

DNCP-014's bounded interface coverage does not fulfill graph-wide discovery.
Graph acceptance would require fixtures for multiple independently released
product libraries including DNCP, colliding local record IDs, declared edges,
cross-node provenance, and missing/stale/versioned nodes, with no canonical
writes. None of federation, synchronization, or this acceptance suite is
implemented by the present documentation clarification.

Reuse implementation: `control_plane\phone_home.py` extends
`capabilities.py`/`fabric.py`; `cli.py`, `mcp_server.py`, and the existing
`ui.py` call one service. Intake is a separate append-only local SQLite inbox.
No canonical incubator records are written, no dispatch occurs, and personal
chat harvesting/model evaluation is not triggered by phone-home launch/check.
The CLI and registry prerequisite is restored without claiming all DNCP-001
release gates complete. Tests use synthetic roots, real MCP stdio negotiation,
HTTP validation, durable/idempotent intake, and isolated wheel/sdist installations.

**User-directed ownership change:** the incubator has drafted provisional
**PRJ-0006**, working title and priorities still undecided. Its canonical project
records are `projects/ai-conversation-hub/README.md`, `BACKLOG.md`, `ROADMAP.md`
in [vvaynethomas/product-incubator](https://github.com/vvaynethomas/product-incubator).
Operator direction is recorded in SRC-0020, linked to SRC-0018/SRC-0019 and
FND-0021/FND-0022. These are references to the producer's draft, not a second
canonical backlog or evidence that queues are synchronized.

| Execution gate | Ownership and next action |
|---|---|
| First: DNCP-014 | Check/review existing capabilities and provide provisional report intake. |
| Next: ChatGPT `conversations.json` | PRJ-0006 ACH-004 intake, with ACH-003 local adapters as relevant; run phone-home first. Do not implement in DNCP-005 here. |
| Then: narrow watcher | PRJ-0006 ACH-005; run phone-home first and use existing adapter/scanner contracts. Do not implement in DNCP-004 here. |
| DNCP retained scope | DNCP-015's first CLI reader targets the pinned local PRJ-0006 v1 contract after phone-home; no new DNCP collector/parser. Broader UI integration and contract approval remain open. |

Preserve DNCP-004/005's existing P1 and DNCP-003 dependency history. **ACH
priorities remain unassigned**; DNCP P1 does not assign producer priorities.
Duplicate-queue reconciliation remains an open owner action. The current DNCP
code remains in place until a separate approved migration; nothing is moved or
refactored on this branch.

Evidence for separation: chat parsing is duplicated across
`control_plane\fabric.py` (bounded conversation harvesters),
`control_plane\handoff.py` (Antigravity discovery/pairing), and
`control_plane\conversations.py` (multi-harness scanners/paste import).
The aggregator product's reported direction is to adopt `copilot-session-tools`
(MIT/PyPI) for Copilot CLI/VS Code and layer ChatGPT/Antigravity adapters;
that product must verify suitability/licensing/version constraints through its
front-door component check rather than treat this direction as tested delivery.

For the producer's universal intake slice, check digital-asset-catalog reuse
before building: `harvesters\snapshot.py` normalized/raw collector provenance,
`harvesters\identity.py` safe hashing and identity evidence, and
`harvesters\filesystem.py` placeholder/streaming-volume/link guards. The catalog
does not parse chats; its asset schema and file identity do not resolve chat
branches/messages. Adopt an appropriate supported interface/shared extraction
later, not copied collectors or imports from a sibling checkout. Producer work
is not implemented here. The bounded consumer follow-up is recorded below.

### DNCP-015 First Consumer Slice (2026-11-02)

`devnet conversation-library --library <explicit-path>` reads the producer
library against main revision `11c362c621727a331a1ecf9ffee40220d8a6d373`.
It preserves every normalized observation, opaque identity, revision, copied
export locator, graph reference, source record, provenance and limitation without
collection, source-URI traversal or DNCP persistence. Version/shape mismatch,
missing/corrupt/busy libraries and bounds fail explicitly. An optional expected
snapshot digest detects changed/deleted observations; original-source freshness
is explicitly unknown, never inferred from conversation dates.

After producer PRJ-0006 PR #39, the reader was aligned to required UTC
`provenance.observed_at` and its bounded read-only transaction semantics:
WAL snapshots are consistent during concurrent writes, while busy/locked errors
are surfaced as safe diagnostics. Unmarked databases remain refused without
initialization; no migration is attempted. Synthetic cross-repo validation
against the merged producer API and its three authored adapter fixtures is
documented in the consumer contract.

See [the consumer contract](docs/conversation-library-consumer.md) for privacy,
limits and synthetic test coverage. Only the CLI/adapter slice is implemented:
Fabric indexing, Conversations UI, Handoff migration, producer contract approval
(DEC-0016 remains draft), real-history acceptance and ownership reconciliation
remain open. No watcher, sync, background scan or automatic handoff is added.

### DNCP-015 Fabric Index Slice (2026-11-09)

`devnet fabric index-hub --library <explicit-path>` streams a version-1 library
read-only into incremental FTS5 tables beside the Fabric index, and
`FabricIndex.search(include_hub=True)`, used by the workbench Fabric tab, returns
those conversations with revision and message locators; phone-home and digest
callers do not opt in. The earlier bounded reader is unchanged and still refuses real-size
libraries; the indexer reads SQLite directly against the same version-1
identifiers rather than through the pinned Hub package. One real library was
indexed to a temporary cache with aggregate evidence only; see
[the consumer contract](docs/conversation-library-consumer.md#fabric-index-over-the-library).
`devnet_search_fabric` accepts `include_conversation_hub` (default false) and the
Conversations tab lists matches from the index. Still open: Handoff integration,
entity-mention links, routing extraction through `material-core`, contract
approval (DEC-0016 remains draft) and owner acceptance. No watcher, sync or
background scan is added.

## Provisional Direction: Repository as the First Digestible Material

The user approved an optional first repository digester as composition of DNCP
pieces, not a new product or mandatory reporting obligation. `control_plane\digester.py`
defines the material-neutral extraction protocol; `control_plane\repo_metabolizer.py`
and `cli.py` provide one implementation and explicit `digest register/list/scan/disable`; a flag records only
opt-in metadata and never triggers scanning. Scan refuses unregistered/disabled
repositories, pins a committed revision (`HEAD` or explicit `--revision`), and extracts bounded static material without
working-tree/Git-state modification, executing repository code, installing
dependencies, LLM calls or external transmission. Phone-home remains optional.

The small material-neutral contract records input material/revision, extractor/
version/time, source paths/blob/digest/line evidence, material items, coverage/
errors/exclusions and residue. Residue preserves bounded notable untargeted
material and repeated observations with counts, explicitly not independence/
corroboration. Limits and omissions are reported, not indiscriminate source copies.

Cached Fabric comparisons provide candidate matches/rationale/provenance with
incomplete inventory warnings, not full product-library graph knowledge or proof
of novelty/trust. Wrong-root/legacy/conversation-containing caches are refused.
Four human dispositions cover mapping to existing capability, trusted solution
to adopt, extend/customize/integrate, and new knowledge/idea; defer/reject remain
review actions, not extra dispositions. No review-event database is added.
The destination product owns its library; the incubator is optional. There is
no automatic adoption, dispatch, source copying, canonical creation, queue
update, intake submission or promotion.

`tests\test_digester.py` verifies consent enforcement, no flag-triggered scan,
unchanged source/Git files including dirty files, deterministic revision evidence,
bounded omissions/residue, actual repetition counts rather than identical display
prefixes, cached-only comparisons, and CLI behavior without phone-home submission.
Reconciliation retains the bounded Git reader and one `digest` CLI while adding
pure typed extraction, historical revision selection, stricter JSON/Markdown/
requirements parsing, repeated candidate counts, private-symbol/unsupported-file
residue, and bounded omitted-file evidence. Combined phone-home/digester tests
cover the integrated branch, including installed packaging and the optional MCP
protocol. See [the shared contract](docs/digester-contract.md).
This does not close DNCP-008/009's earlier graph/blackboard/background requirements.
Syft/SCIP remain conditional specialist candidates, not dependencies of this slice;
catalog patterns are prior art only. See the README for exact limits and supported
static formats. No scheduled scan, other material digester, concierge or router
is implemented.

## Explicit Material-Adapter Follow-On

The bounded `kind: "material"` phone-home slice in `docs/material-ingestion.md`
now includes a JSON adapter in the current checkout. It records object/array
structure and primitive values as bounded provisional observations with
deterministic JSON Pointer evidence, repetition counts, source hashes and
untargeted residue. Parse errors and depth/record/display limits remain visible;
the adapter does not infer schema, trust, canonical status or intent. CLI
`.json` inference and the existing shared submit pathway use the same digester.
This does not alter whole-repository scanning or the separate conversation
aggregator.

TOML remains deferred: the package supports Python 3.10, where `tomllib` is not
in the standard library, and this slice does not justify adding a dependency.
Broader schema/semantic extraction, streaming input and other formats remain
unimplemented.
