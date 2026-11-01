# Development Network Control Plane (DNCP)

**Autonomous Nervous System, Single Pane of Glass, and Cross-Platform Interaction Command Center for Development Networks.**

`devnet-control-plane` is an autonomous system node designed to sit **above** all repositories in a local development network (e.g. `GitHub-Repos/*`). It eliminates manual "human message bus" overhead by providing unified visibility, queue management, cross-harness chat sync, capability discovery, and interaction frame evaluation.

**Checkout status (2026-11-01):** 0.1.0 is the declared package version, not a verified published release. The six-tab workbench and core engines are present, but the CLI module and installed-package registry are missing. Conversation discovery runs on request, not in a background watcher; external ingestion currently accepts raw text only. See [BACKLOG.md](BACKLOG.md) for evidence and acceptance gates and [ROADMAP.md](ROADMAP.md) for planned work.

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

The read-only endpoint is `/api/decision-aid?topic=capability-routing&context=local-only`; the GUI uses `/?tab=capabilities&aid_topic=capability-routing`. Context is not persisted by DNCP, but GET URLs may appear in browser history; never enter secrets. The helper can also be called from a source checkout independently of the currently missing CLI:
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

**Intended CLI workflow, currently blocked:** both console scripts below reference `control_plane.cli:main`, which is absent in this checkout. Installation alone does not make these commands usable. Clean-package launch and registry loading must be verified before this quickstart can be treated as working.

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

### 3. CLI Commands
```bash
# Unified status across all 6 pillars and discovered repos
devnet status

# Search knowledge records, ADRs, and indexed chats
devnet search "InteractionFrame"

# Discover existing code modules and patterns before writing new tools
devnet discover "sqlite search"

# Compile a 1-click Context Handoff Packet for another AI model
devnet handoff --turns 3 --clip

# Run side-by-side prompt evaluations
devnet eval-frames --task "Design a benchmark" --frames baseline_direct cute_mentor_builder
```

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

**Not yet release-ready:** builds omit the top-level frame registry from the wheel and reference the missing CLI module. Archive timestamps prevent assuming byte-for-byte reproducibility, and manifest Git provenance is resolved outside this repository. No tags or GitHub Releases were listed during the 2026-11-01 audit; publication elsewhere is unknown. Artifact creation and SHA-256 digests alone do not establish installability or acceptance.

Intended CLI integrity check (also blocked by the missing CLI):
```bash
devnet verify-release dist/RELEASE_MANIFEST.json
```
