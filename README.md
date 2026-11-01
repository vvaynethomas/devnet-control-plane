# Development Network Control Plane (DNCP)

**Autonomous Nervous System, Single Pane of Glass, and Cross-Platform Interaction Command Center for Development Networks.**

`devnet-control-plane` is an autonomous system node designed to sit **above** all repositories in a local development network (e.g. `GitHub-Repos/*`). It eliminates manual "human message bus" overhead by providing unified visibility, queue management, cross-harness chat sync, capability discovery, and interaction frame evaluation.

**Checkout status (2026-11-01):** 0.1.0 is the declared package version, not a verified published release. The six-tab workbench, CLI, installed registry, and local phone-home front door are present. Conversation discovery still runs on request; external ingestion accepts raw text only. Future collection belongs to the provisional standalone **PRJ-0006** chat product; DNCP retains consumer integration. See [BACKLOG.md](BACKLOG.md) for historical audit evidence, current acceptance gates, and ownership handoff; see [ROADMAP.md](ROADMAP.md) for planned work.

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

The incubator remains the source of truth; DNCP does not copy the supplied notes or create a second knowledge store. Configure `FACTORY_ROOT` to the intended incubator checkout. The aid reads current records through the existing Fabric collector; rebuild Fabric after canonical changes to refresh linked entity inspectors. A missing directory or read failure is reported explicitly; no tagged records means guidance is unavailable, not that no relevant capability exists.

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
The declared package requires Python >=3.10 and no mandatory external runtime dependencies. Editable/source builds use `setuptools>=61.0` and `wheel`; the standard-library release builder is a separate path. Intended installation:
```bash
pip install -e .
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

**Intake is an inbox, not another knowledge store.** Submissions append to
`DEVNET_DATA_DIR\phone_home.sqlite` with an `INTAKE-<UUID>`, UTC receipt,
digest, and fixed `provisional` status. The canonical incubator owns SRC/FND/PAT/DEC.
Source/session references, reuse queries, and external evidence are unverified
claims; nothing is fetched, executed, approved, or automatically promoted.
Idempotency keys return the same receipt for identical normalized content and
conflict on changed content. There is no mutation/deletion/promotion interface.
A human reviews/export submissions and separately creates/updates canonical
incubator records under its existing contract.

Required fields: kind, title, summary, source_repo, reuse_query. Kinds:
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

Only `serve`, `mcp`, `phone-home`, version/help are implemented CLI commands.
Earlier intended status/search/discover/handoff/eval-frames/verify-release CLI
commands remain unimplemented; their engines/UI are not promises of CLI support.

### Next round and ownership

Phone-home is DNCP-014, first. The incubator has drafted provisional **PRJ-0006**
in `projects/ai-conversation-hub/`; working title and priorities are undecided.
DNCP-005 collection maps to its ACH-004 intake; DNCP-004 maps to ACH-005 watcher.
ACH-003 owns local adapters. The user-directed reuse direction is to adopt
`copilot-session-tools` (reported MIT/PyPI) for Copilot CLI/VS Code and add
ChatGPT/Antigravity adapters, subject to the product's own front-door and component
verification. DNCP-015 is only a consumer-integration proposal, not another
collector backlog. Owner reconciliation of duplicate queues remains open.
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

`release.py` uses only the Python standard library to construct local artifacts declared as 0.1.0 under **DEC-0015**:
```bash
python release.py
```
Outputs:
* Wheel: `dist/devnet_control_plane-0.1.0-py3-none-any.whl`
* Source: `dist/devnet_control_plane-0.1.0.tar.gz`
* Manifest: `dist/RELEASE_MANIFEST.json` with cryptographic SHA-256 digests.

**Remaining release gates:** CLI and registry installation have portable smoke coverage for both the standard-library wheel and the setuptools wheel built from its sdist. Archive timestamps still prevent assuming byte-for-byte reproducibility, and manifest Git provenance is resolved outside this repository. No tags or GitHub Releases were listed during the 2026-11-01 audit; publication elsewhere is unknown. These checks do not establish publication or operator acceptance.

Planned CLI integrity check (not implemented):
```bash
devnet verify-release dist/RELEASE_MANIFEST.json
```
