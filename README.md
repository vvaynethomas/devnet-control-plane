# Development Network Control Plane (DNCP)

**Autonomous Nervous System, Single Pane of Glass, and Cross-Platform Interaction Command Center for Development Networks.**

`devnet-control-plane` is an autonomous system node designed to sit **above** all repositories in a local development network (e.g. `GitHub-Repos/*`). It eliminates manual "human message bus" overhead by providing unified visibility, queue management, cross-harness chat sync, capability discovery, and interaction frame evaluation.

**Checkout status (2026-11-01):** 0.1.0 is the declared package version, not a verified published release. The six-tab workbench, CLI, installed registry, and local phone-home front door are present. Explicit material ingestion covers bounded text/Markdown, CSV, HTML, JSON, Python and ZIP; conversation discovery still runs on request and its legacy external-chat importer accepts raw text only. Future chat collection belongs to the provisional standalone **PRJ-0006** chat product; DNCP retains consumer integration. See [BACKLOG.md](BACKLOG.md) for historical audit evidence, current acceptance gates, and ownership handoff; see [ROADMAP.md](ROADMAP.md) for planned work.

---

## The 6 Pillars

| Pillar | Engine | Purpose & Capability |
| :--- | :--- | :--- |
| **1. Portfolio & Network** | `control_plane/portfolio.py` | Scans discovered sibling repositories across the configured development network (count varies), reports live Git states, branches, dirty files, and stewardship tiers. |
| **2. Queues & Work Tracking** | `control_plane/queues.py` | Aggregates work backlogs across all incubated products and sibling repositories. Features the data-driven **PAT-0001 Next-Action Router**. |
| **3. Knowledge & Conversation Fabric** | `control_plane/fabric.py` | Rebuildable SQLite FTS5 search index across architecture records (SRC, FND, PAT, DEC, ART), runbooks, and indexed AI conversation logs. |
| **4. Conversations, Handoff & Tokenomics** | `control_plane/conversations.py`<br>`control_plane/handoff.py` | Request-time discovery of Antigravity, VS Code Copilot, and Copilot CLI sessions; raw-text cloud transcript import and character-based token estimates. Granular copy buttons cover turn, prompt, response, and code; full handoffs currently compile Antigravity sessions only. Imported chats are not yet indexed into Fabric. |
| **5. Capability Discovery** | `control_plane/capabilities.py` | "Have we solved this before? Do we have a tool?" Scans local code modules using Python AST parsing to prevent duplicate tool creation. |
| **6. Interaction Lab** | `control_plane/interaction_lab.py` | Composable `InteractionFrame` engine (Presentation, UserModel, AssistantModel, Relationship). Runs side-by-side prompt benchmarks with human rubric rating. |

### Read-Only Decision Aid (Unreleased Integration)

Capability Discovery now includes a **Decision Aid** for infrastructure/hosting, coordination/recoverability, and capability/context routing. Select a topic and enter non-sensitive project constraints to review canonical incubator guidance, unranked alternatives, review questions, record statuses, and upstream provenance. Inputs remain unverified and do not change ranking or establish tool access. No provider is selected, no assignment is dispatched, and no deployment or approval is performed. Existing capability search remains available alongside the aid.

The incubator remains the source of truth **for the incubator-owned records consumed by this aid**, not for every product library in the network. DNCP does not copy the supplied notes or create a second canonical store for those records. Configure `FACTORY_ROOT` to the intended incubator checkout. The aid reads current records through the existing Fabric collector; rebuild Fabric after canonical changes to refresh linked entity inspectors. A missing directory or read failure is reported explicitly; no tagged records means guidance is unavailable, not that no relevant capability exists.

**Record contract:** use existing Fabric-supported directories (`knowledge/`, project READMEs/artifacts, runbooks/workflows) and scalar frontmatter `id`, `title`, `type`, `status`, `created_date`; use inline arrays for `tags`, `upstream_refs`, and `downstream_refs`. Include one or more exact topic tags: `infrastructure-decision`, `coordination-recoverability`, `capability-routing`. Record IDs are discovered, not hardcoded. Provisional labels, unresolved references, and missing dates stay visible; neither record status nor a source's vendor opinion proves current operational readiness.

The read-only endpoint is `/api/decision-aid?topic=capability-routing&context=local-only`; the GUI uses `/?tab=capabilities&aid_topic=capability-routing`. Context is not persisted by DNCP, but GET URLs may appear in browser history; never enter secrets. The helper can also be called directly from an installed package or source checkout:
```python
from pathlib import Path
from control_plane.decision_aid import build_decision_aid

aid = build_decision_aid(
    factory_root=Path("path-to-incubator"),
    topic="capability-routing",
    operator_context="Need repository editing; access has not been verified.",
)
```

---

## Architectural Relationship to ALM (Agent Lifecycle Management)

* **ALM (`agent-lifecycle-management`):** The intended specialized platform for authoring, versioning, calibrating, and benchmarking agent prompts, skills, and orchestrations for network repositories. Network-wide consumption is an architectural goal, not verified by this checkout.
* **DNCP (`devnet-control-plane`):** The top-level operational control plane and nervous system intended to coordinate repositories, track work, aggregate conversations, and monitor health. Automated consumption of versioned ALM skills/prompts is planned under DNCP-012, not implemented in this checkout.

---

## Quickstart

The CLI works from other repository sessions after local installation. Configure
one canonical incubator root, network root, and shared writable runtime directory
for all clients. DNCP never writes knowledge records to that incubator.

### 1. Installation
The declared package requires Python >=3.10 and the exact local dependency
`material-core==0.1.0`; editable/source builds use `setuptools>=61.0` and
`wheel`. Build the core artifact first as documented in
[the package handover](docs/material-core-package.md), then install/build DNCP
with that local wheelhouse. The standard-library release builder is a separate path.
```bash
pip install --no-index --no-build-isolation --find-links dist/material-core -e .
```

Verify CLI installation:
```bash
devnet --version   # devnet 0.1.0
```

### 2. Start the Loopback Web Workbench
Launch the local loopback GUI on `http://127.0.0.1:8780/`:
```bash
devnet serve --port 8780
```
Open **`http://127.0.0.1:8780/`** to access all 6 tabs in your browser.

Launch binds to loopback only and does not seed model evaluations or harvest
personal chats. Explicit Interaction Lab evaluations remain available in the UI.

### 3. Network phone-home

#### Library architecture: product nodes, not one central library

**The network library is a graph of the network's product libraries.** Each
product ships its own library with its release and owns its records, capabilities,
and provenance. DNCP has its own library as a product, while the control plane
must surface or attend the graph across product nodes. The incubator is one
owner/source in that graph; it is not the canonical owner of all network knowledge.
This is the intended architecture, **not implemented graph-wide discovery**.

Current phone-home coverage is narrower:

| Surface | What is implemented | What it does not establish |
|---|---|---|
| Knowledge and provenance | `control_plane\fabric.py` collects records and skill/prompt registries from one `FACTORY_ROOT`, with record-reference resolution in that index. | Discovery of independently released product libraries, graph node/edge identity, or cross-product provenance resolution. |
| Registered tools and owner candidates | `control_plane\capabilities.py` and `phone_home.py` consume that incubator's skill/runbook/pattern/project registries. | Every product's own registry, library contract, released version, or current capabilities. |
| Local modules | `scan_network_modules()` reads DNCP's `control_plane` modules, selected incubator roots, and bounded Python modules in discovered sibling Git checkouts. | A released product-library inventory. A checkout name/path and AST symbol are not a product-library node or release identity. |
| DNCP's own distribution | The package ships DNCP code and the InteractionFrame registry; its own Python modules are searchable. | A declared/versioned DNCP library manifest or proof that DNCP's complete product library is published and graph-addressable. |
| Reports | A separate local provisional inbox captures unverified source/evidence references for manual review. | Canonical ownership, product-library publication, promotion, or synchronization. |

Specific follow-on gaps: a product-owned library/release contract (including
DNCP's), node discovery and declared graph edges, namespaced identity across
products/releases, cross-node queries and provenance, per-node freshness/
availability/version evidence, and destination-owner review of reported
discoveries. Existing record IDs and upstream/downstream refs retain their
incubator contract; do not reinterpret them as a verified network graph.
No federation, synchronization, node dispatch, or release-library implementation
is added by this clarification. An empty current check cannot establish absence
across the intended graph.

**Priority 1 decision order:** (1) find an existing network capability and reuse
it with customization, citing evidence; (2) check for a battle-tested external
solution/component to leverage; (3) scope an extension/new capability in an
existing registry product; (4) consider a standalone product only with an
explained ownership boundary and independent value to the network and/or outside
users. Stop at evidence for the earliest step; expose unknowns. Text matches
are candidate evidence, not verified suitability, readiness, or approval. The
human makes the final choice; no agent is dispatched.

All four interfaces return the same `schema_version: 1` check contract, including
`decision_ladder`, provenance/status, coverage, freshness, warnings, and separately
labeled provisional intake. Step 2 always says **external check not performed**:
there are no live external requests or fabricated candidates. When the network
check has no match, the ladder stops at unresolved step 2 rather than silently
choosing a new product. Registry products are named as unevaluated candidate
owners, not automatically assigned. Standalone justification requires resolved
reuse/component checks, no suitable existing owner, independent network/outside
value, and human approval of ownership and maintenance.

Configure the same paths for CLI, API server, and MCP. PowerShell example:

```powershell
$env:FACTORY_ROOT = 'C:\path\to\product-incubator'
$env:DEV_NETWORK_ROOT = 'C:\path\to\GitHub-Repos'
$env:DEVNET_DATA_DIR = 'C:\path\to\shared-devnet-runtime'
devnet phone-home check "sqlite ingestion" --json
devnet phone-home rebuild
devnet serve --port 8780
```

Defaults: runtime data is in the user's `.devnet` directory, independent of the
calling repository; Factory/network roots use existing discovery. Explicit
`--factory-root`, `--network-root`, `--data-dir` options go **before** the command.
Runtime directories inside Git repositories or the canonical incubator are
rejected. A CLI/source alternative is `python -m control_plane.cli` after
installation (or with an explicitly configured checkout module path).

Checks reuse Fabric and Capability Discovery. Initial cache creation indexes
canonical records only and is disclosed; later checks report the Fabric rebuild
timestamp (unknown for legacy indexes). `phone-home rebuild` explicitly refreshes
canonical records without harvesting chats. A cache from a different configured
canonical root requires an explicit rebuild, not silent cross-root reuse.
Existing Fabric rebuild actions can
still include their bounded legacy conversation sources. Current registry/module
reads and cached knowledge have different freshness. Missing roots, registries,
or unreadable modules are warnings, not proof no reusable capability exists.
Module discovery reads DNCP, incubator module roots, and discovered sibling Git
checkouts; it is Python-only, skips caches/links, and caps traversal at eight
levels, 2,000 files, and 1 MiB per module. It is not a complete network inventory.
Registry permissions may expose local file paths to any client running as the
same OS user; loopback is not authentication against other local users.

Submit a JSON file after checking, for example:

```json
{
  "schema_version": 1,
  "kind": "tool",
  "title": "Reusable import adapter",
  "summary": "What it does, constraints, and evidence to review.",
  "source_repo": "owner/repository",
  "reuse_query": "conversation import",
  "source_session": "local-session-reference",
  "source_ref": "path, commit, or URL (not fetched)",
  "related_refs": ["FND-0021"],
  "tags": ["ingestion"],
  "external_evidence": "Unverified external candidate link and evaluation notes, if any.",
  "idempotency_key": "repo-session-discovery-1"
}
```

```powershell
devnet phone-home submit --file report.json
devnet phone-home intake list --limit 20 --offset 0
devnet phone-home intake get INTAKE-returned-uuid
devnet phone-home intake export INTAKE-returned-uuid
```

Output is JSON on stdout; failures go to stderr with a nonzero exit code.
`--file -` reads a bounded JSON request from stdin. JSON export also goes to
stdout so the caller can redirect it to their chosen review artifact.

**Intake is an inbox, not another canonical product library.** Submissions append to
`DEVNET_DATA_DIR\phone_home.sqlite` with an `INTAKE-<UUID>`, UTC receipt,
digest, and fixed `provisional` status. The incubator retains ownership of the
SRC/FND/PAT/DEC records actually stored under its existing contract; that does
not make it the owner of every product's released library.
Source/session references, reuse queries, and external evidence are unverified
claims; nothing is fetched, executed, approved, or automatically promoted.
Idempotency keys return the same receipt for identical normalized content and
conflict on changed content. There is no mutation/deletion/promotion interface.
A human reviews/exports submissions and separately creates/updates incubator-owned
records under that existing contract where appropriate. Product-owned discoveries
require review by their destination product owner; product-library routing and
promotion are not implemented by this local inbox.

For report submissions, required fields: kind, title, summary, source_repo, reuse_query. Report kinds:
discovery/tool/skill/runbook/module/finding/decision. Optional schema version
defaults to 1; other versions and unknown fields fail. Bounds: 64 KiB serialized
request, 200-character title, 20,000-character summary/external evidence,
2,000-character query, 1,000-character source/session/key, 20 tags/refs of at
most 200 characters, and 1-50 results per response (paginated inbox). GET queries
are not persisted by DNCP, but can appear in browser/server/client history.

Never submit secrets or sensitive information. Known token patterns are rejected
before storage, but detection is incomplete. This SQLite inbox is **not encrypted**.
No credentials, external services, paid hosting, or repository dispatch are involved.

### API and human UI

Use the existing **Capability Discovery** tab: Decision Aid and existing search
remain; phone-home adds a check, provisional report form, inbox, and JSON export.

| HTTP interface | Purpose |
|---|---|
| `GET /api/phone-home/check?q=...&limit=20` | Shared reuse check and ordered ladder |
| `POST /api/phone-home/submissions` | JSON intake; `Content-Type: application/json` |
| `GET /api/phone-home/submissions?q=...&limit=20&offset=0` | Paginated inbox/export |
| `GET /api/phone-home/submissions?id=INTAKE-...` | Submission detail/export |

Successful submission returns HTTP 201. Validation, conflict, size, and storage
errors are explicit (400/409/413/503); unknown IDs return 404. The server requires
a loopback Host, forbids cross-origin writes, and protects the UI form with CSRF.
Local JSON clients may omit Origin; no CORS access is granted.

### MCP (optional, local stdio)

Install locally with `pip install -e ".[mcp]"` (or install the built wheel's `mcp`
extra). The official SDK is optional; without it, `devnet mcp` fails with an
actionable installation message. Configure the MCP client's command as the
installed `devnet` executable with arguments `["mcp"]` and the same three root/
data environment variables above. Alternatively use an absolute Python executable,
arguments `["-m", "control_plane.cli", "mcp"]`, and those variables.

Tools: `phone_home_check(query, limit)`, `phone_home_submit(...)`,
`phone_home_list(query, limit, offset)`, `phone_home_get(submission_id)`.
Submit exposes the JSON fields above; tool errors are SDK error results, not
successful empty answers. Stdio uses SDK negotiation and no HTTP MCP or external
connections. This bounded capability/intake adapter does **not** finish DNCP-010's
planned live-state/Metabolizer/handoff server.

Only `serve`, `mcp`, `phone-home`, `digest`, `conversation-library`, version/help are implemented CLI commands.

**DNCP-015 first consumer slice:** `devnet conversation-library --library
'C:\Private\ConversationHub\library.sqlite'` explicitly reads a producer
version-1 library without collection or persistence. It prints unredacted
normalized observations and provenance locally; `--expected-snapshot` rejects
changed evidence. Reads use one read-only SQLite snapshot (including WAL) and
preserve the producer's import-observation timestamp separately from unknown
original-source freshness. See the
[consumer contract and privacy limits](docs/conversation-library-consumer.md).
Existing Fabric, Conversations and Handoff surfaces are not migrated.

Earlier intended status/search/discover/handoff/eval-frames/verify-release CLI
commands remain unimplemented; their engines/UI are not promises of CLI support.

### General material ingestion: one explicit submission

Material is not limited to repositories or products. Explicitly supplied
text/Markdown, CSV, HTML, JSON, Python source and ZIP containers use format adapters
and the existing phone-home inbox, with **no repo opt-in, product membership,
agent report or bilateral acceptance**. The provisional inbox is not a second
acceptance stage; only consequential later execution/adoption/canonical promotion
requires human approval. Bounded static extraction stays local; input is never
executed or fetched, and no LLM or automatic promotion is involved.

The deterministic evidence contract and supplied-byte adapters live in the
repository-local `material_core` package. DNCP's `control_plane\material_ingestion.py`
validates the phone-home payload and delegates to that core; phone-home still
owns routing, receipt metadata and inbox persistence. This is a consumer boundary
inside the DNCP distribution, not a separately released product or handover.

```powershell
devnet phone-home ingest 'C:\inputs\notes.md' --target reuse
devnet phone-home ingest 'C:\inputs\bundle.zip'
```

The same `kind: "material"` JSON variant works with existing CLI `submit`,
loopback `POST /api/phone-home/submissions` and MCP `phone_home_submit`.
Input identity/hash/member/line/JSON-pointer provenance, observations,
explicitly declared direction, coverage gaps and bounded untargeted residue are retained separately
from canonical knowledge. Repetition remains a frequency signal, not waste.
The existing human UI remains a report form and shared inbox/export, not an
upload form. JSON contributes bounded object/array structure and canonical scalar
observations only; it does not infer schema or meaning. TOML remains deferred
because Python 3.10 is supported and there is no justified dependency. See
[exact formats, submission schema and limits](docs/material-ingestion.md):
32 KiB inputs, 32 ZIP entries, 32 KiB/member, 128 KiB total uncompressed,
100:1 maximum ratio, no links/path traversal/encryption/nested extraction.
Only bounded evidence is persisted locally, not raw input/base64; that evidence
can include text snippets and is unencrypted.

### Repository metabolizer: opt-in whole-repository scanning

**Provisional direction:** a repository is one kind of material the network
can digest into reviewable evidence, ideas, and reusable capability candidates.
This is a composition of DNCP observation, Python AST extraction and cached
Fabric search, not a new product, mandatory agent reporting protocol, or
centralized owner of other products' libraries. Phone-home remains optional.

Opt-in gates later whole-repository scans only, never explicitly supplied files.
Registering records consent metadata only; **it never scans**. A separate explicit
command reads one pinned committed revision (`HEAD` by default). Unregistered or disabled
repositories are refused before repository observation:

```powershell
devnet digest register 'C:\path\to\selected-repository'
devnet digest list
devnet digest scan 'C:\path\to\selected-repository' --target 'sqlite reuse'
devnet digest scan 'C:\path\to\selected-repository' --revision '<commit-or-ref>'
devnet digest disable 'C:\path\to\selected-repository'
```

Use the shared `--data-dir` option before `digest` if needed. Registration lives
in local `digester.sqlite` outside Git repositories. Output is JSON on stdout;
redirect it to an explicitly chosen local review file to retain it. The digester
itself stores no bundles, source copies, scan history, or reports. There is no
watcher, scheduled scan, forced reporting, automatic intake submission, promotion,
queue update, code copying, adoption, dispatch, or execution.

**Read-only scope:** the selected repository root is verified using read-only Git
plumbing, then its commit/tree/blob identities are pinned. Dirty/untracked working
files, symlinks, submodules, generated/vendor/cache directories, secret-like
filenames, and recognized token-bearing contents are excluded. Repository Git
state/config/index and working files are untouched. No repository code, hooks,
install scripts, filters, or dependencies are executed/installed. Git lazy fetch
and credential prompting are disabled; missing local objects cause explicit
failure rather than remote ingestion. No LLM, extractor download, external
transmission, or paid service is needed. Detection is incomplete: review bundles
locally and do not transmit potentially sensitive evidence indiscriminately.

The shared [material-neutral contract](docs/digester-contract.md) is implemented
in `material_core\contract.py` and re-exported by `control_plane\digester.py` for
compatibility. `material_core\supplied.py` implements deterministic supplied-byte
extraction without DNCP orchestration. `control_plane\repo_metabolizer.py` remains
the Git-aware repository extractor plus opt-in registration and cached comparison;
it reads pinned Git objects and is not part of the pure byte-processing API.
There is no separate `metabolizer` CLI or competing scan/review database.

The versioned **material-neutral bundle** includes the repository input reference,
exact revision and committed-view semantics; extractor name/version, Git version
and observation time; extracted material items; file/blob/SHA-256/path/line
provenance with literal `git:<revision>:<path>` evidence references; coverage,
exclusions/errors; residue; cached comparison; and provisional human-review
options. Module/manifest/config/dependency evidence marks file-level location
precision rather than claiming a parsed dependency line; symbols/headings and
notable observations retain their source lines. Display truncations are flagged
and counted. Evidence references are not clickable remote URLs or instructions.
`git show <revision>:<path>` can resolve them manually in that repository.
`evidence_digest` covers stable extracted content and comparison context excluding
the observation timestamp; identical revision, extractor and cache context give
the same digest. It does not assert correctness, trust, or file-independent evidence.

Recognized first-slice inputs: Markdown headings/notable TODO/idea/decision/
limitation/warning lines, bounded Python module docstrings/top-level exported
symbols/import observations, `package.json`/`composer.json` dependency declarations,
simple `requirements*.txt` declarations, `pyproject.toml`, `Cargo.toml`, `go.mod`,
selected configuration files and `.github` YAML configuration. Markdown fences
are excluded from topic/notable-line extraction; private symbols, non-targeted
manifest fields, unsupported files and unparsed requirement directives remain
bounded residue. Duplicate JSON fields and malformed dependency groups are
reported as errors, not accepted as partial manifests. TOML/Go manifest declarations remain
static evidence, not fully parsed/resolved dependencies. There is no complete
SBOM, cross-language symbol graph, runtime behavior analysis, or unrestricted
source summarization. Syft is a candidate only if a resolved dependency/SBOM gap
is proven; SCIP requires an actual symbol-graph use case. Repomix and LLM calls
are not prerequisites. Catalog snapshot/identity/triage patterns are prior art,
not copied modules or runtime imports from another checkout.

Bounds: at most 1 MiB of Git tree metadata (excess is an explicit refusal),
100 recognized files, 128 KiB per file, 1 MiB total content, 100 material items,
1,000 notable observations, 30 residue groups with at most three evidence refs
and 300 display characters each, 100 omitted-file evidence references, and ten
comparison queries with five cached matches each. Files/items/observations and
evidence references beyond limits have counted omissions.
Repeated full normalized observations get occurrence counts and digests;
distinct long texts are not merged merely because their display prefixes match.
Residue retains notable untargeted material and repetitions as **frequency
signals only**, never independence, corroboration, trust, or fabricated
serendipity. There is no claim to preserve every possible insight from a repository.

Comparison uses only the **already-built, matching-root, canonical-only Fabric cache** in the chosen data
directory; it never initializes/rebuilds that cache or scans other repositories/
registries/modules. Available capability/product records are only those already
represented in the cache. Missing/corrupt cache is explicitly unavailable with
no-match/novelty uncertainty; wrong-root, legacy and conversation-containing
caches are not searched. Cache timestamps/root provenance and incomplete
product-library graph coverage remain visible. Ordinary phone-home checks and
their optional module discovery are separate operations, not triggered by
digestion. There is no external component search.

Proposals cite material evidence, query, cached matches/status/provenance, and
text-relevance rationale. The four human dispositions are **maps to existing
capability**, **trusted solution to adopt**, **extend/customize/integrate**, and
**new knowledge/idea**; **defer** and **reject** are separate review actions.
These are advisory options, not automatic classifications or persisted review
events. Even choosing adoption is a human judgment, not an adoption operation.
Similarity does not prove trust; no match does
not prove novelty. The destination product owns its library. The incubator is
an optional human-governed destination, not mandatory ownership or automatic
canonical record creation. Only the user/product owner chooses what to retain,
customize, integrate, or set aside.

### Next round and ownership

Phone-home is DNCP-014, first. The incubator has drafted provisional **PRJ-0006**
in `projects/ai-conversation-hub/`; working title and priorities are undecided.
DNCP-005 collection maps to its ACH-004 intake; DNCP-004 maps to ACH-005 watcher.
ACH-003 owns local adapters. The user-directed reuse direction is to adopt
`copilot-session-tools` (reported MIT/PyPI) for Copilot CLI/VS Code and add
ChatGPT/Antigravity adapters, subject to the product's own front-door and component
verification. DNCP-015 now has a bounded explicit-path CLI consumer against a
pinned version-1 library, not another collector backlog; Fabric, Conversations
and Handoff migration and owner acceptance remain open. Owner reconciliation
of duplicate queues remains open.
Each follow-on must run the phone-home check before design/code.

Foundations to extend: `fabric.py` collector/FTS5/provenance, `capabilities.py`
registries/AST, `portfolio.py` project registry, `conversations.py` scanners/paste
import, `handoff.py`, and `interaction_lab.py`. Parsing is currently duplicated
across Fabric, Handoff, and Conversations; export parsing, imported-chat indexing,
all-harness handoffs, and background updates are not solved by this front door.
The asset catalog does not ingest chats. For PRJ-0006, inspect its
`harvesters\snapshot.py` versioned collector envelopes,
`harvesters\identity.py` safe hashes/identity evidence, and
`harvesters\filesystem.py` placeholder/link guards before rebuilding those pieces.
Use a supported shared interface/extraction proposal, not copied modules or a
runtime import from a sibling checkout. No chat code is moved/refactored here.

---

## Packaging and Release

`release.py` uses only the Python standard library to construct local artifacts
declared as 0.1.0 under **DEC-0015**. It requires an explicitly built
`material-core==0.1.0` wheel and validates its identity; it never embeds the core:
```bash
python build_material_core.py --output-dir dist/material-core
python release.py --material-core-wheel dist/material-core/material_core-0.1.0-py3-none-any.whl --output-dir dist/devnet
pip install --no-index --find-links dist/material-core dist/devnet/devnet_control_plane-0.1.0-py3-none-any.whl
```
The core and DNCP each emit their own wheel/source archive and
`RELEASE_MANIFEST.json` with artifact/source SHA-256 identities. The DNCP
manifest pins the exact core wheel by filename and digest.

**Remaining release gates:** CLI and registry installation have portable smoke coverage for both the standard-library wheel and the setuptools wheel built from its sdist. Archive timestamps still prevent assuming byte-for-byte reproducibility, and manifest Git provenance is resolved outside this repository. No tags or GitHub Releases were listed during the 2026-11-01 audit; publication elsewhere is unknown. These checks do not establish publication or operator acceptance.

Planned CLI integrity check (not implemented):
```bash
devnet verify-release dist/RELEASE_MANIFEST.json
```
