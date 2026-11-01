# Development Network Control Plane (DNCP)

**Autonomous Nervous System, Single Pane of Glass, and Cross-Platform Interaction Command Center for Development Networks.**

`devnet-control-plane` is an autonomous system node designed to sit **above** all repositories in a local development network (e.g. `GitHub-Repos/*`). It eliminates manual "human message bus" overhead by providing unified visibility, queue management, cross-harness chat sync, capability discovery, and interaction frame evaluation.

---

## The 6 Pillars

| Pillar | Engine | Purpose & Capability |
| :--- | :--- | :--- |
| **1. Portfolio & Network** | `control_plane/portfolio.py` | Scans all 22+ sibling repositories across the development network, reports live Git states, branches, dirty files, and stewardship tiers. |
| **2. Queues & Work Tracking** | `control_plane/queues.py` | Aggregates work backlogs across all incubated products and sibling repositories. Features the data-driven **PAT-0001 Next-Action Router**. |
| **3. Knowledge & Conversation Fabric** | `control_plane/fabric.py` | Rebuildable SQLite FTS5 search index across architecture records (SRC, FND, PAT, DEC, ART), runbooks, and indexed AI conversation logs. |
| **4. Conversations, Handoff & Tokenomics** | `control_plane/conversations.py`<br>`control_plane/handoff.py` | Unified chat command center. Auto-harvests Antigravity and VS Code Copilot chats, ingests Microsoft Copilot / cloud exports, computes tokenomics, and provides **1-click granular copy controls** (full handoff packet, turn, prompt, response, or code only). |
| **5. Capability Discovery** | `control_plane/capabilities.py` | "Have we solved this before? Do we have a tool?" Scans local code modules using Python AST parsing to prevent duplicate tool creation. |
| **6. Interaction Lab** | `control_plane/interaction_lab.py` | Composable `InteractionFrame` engine (Presentation, UserModel, AssistantModel, Relationship). Runs side-by-side prompt benchmarks with human rubric rating. |

---

## Architectural Relationship to ALM (Agent Lifecycle Management)

* **ALM (`agent-lifecycle-management`):** The specialized platform for authoring, versioning, calibrating, and benchmarking agent prompts, skills, and orchestrations. Every repository in the network consumes from ALM to equip and improve its local agents.
* **DNCP (`devnet-control-plane`):** The top-level operational control plane and nervous system that coordinates all repositories, tracks work, aggregates conversations, and monitors health. DNCP itself consumes from ALM for its own agent maintenance!

---

## Quickstart

### 1. Installation
Install as an editable package or from a built wheel (requires Python >=3.10, zero external pip dependencies):
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
# Unified status across all 6 pillars and 22 repos
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

Built with a deterministic, zero-dependency release pipeline adhering to **DEC-0015**:
```bash
python release.py
```
Outputs:
* Wheel: `dist/devnet_control_plane-0.1.0-py3-none-any.whl`
* Source: `dist/devnet_control_plane-0.1.0.tar.gz`
* Manifest: `dist/RELEASE_MANIFEST.json` with cryptographic SHA-256 digests.

Verify release integrity:
```bash
devnet verify-release dist/RELEASE_MANIFEST.json
```
