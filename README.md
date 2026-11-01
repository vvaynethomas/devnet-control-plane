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
