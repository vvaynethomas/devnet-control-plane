# UI/UX Specification: Universal Conversation Mesh & The Metabolizer
**Product:** Development Network Control Plane (DNCP)
**Status:** Proposed implementation target (v0.2.0 - v0.3.0); approval and delivery acceptance unverified
**Primary Focus:** Low-Touch Multi-Harness Chat Ingestion, Epistemic Alignment, and Anti-Fatigue Handoff Controls

---

**Evidence boundary (2026-11-01):** This document specifies intended behavior, not shipped functionality. The current checkout has request-time local scans, raw-text imports into an ordinary local SQLite hub, and granular copy buttons with inline feedback. It does not implement the watcher, platform export/drop-zone parsers, imported-chat FTS5 indexing, gateway, epistemic matrix, blackboard, Metabolizer, MCP server, or shortcuts below. Full handoff compilation supports Antigravity only. Wireframe dates, agent states, digests, repository counts, and release/review claims are illustrative, not live or verified records. See [the backlog](../BACKLOG.md) for acceptance gates.

## 1. Executive Summary & Problem Definition

Developers working with multiple modern AI coding agents (Antigravity, VS Code GitHub Copilot, Microsoft 365 Copilot, Google Gemini Chat, OpenAI ChatGPT, Anthropic Claude, Perplexity) face three debilitating friction points:

1. **The "Human Copy-Paste Bus" Bottleneck:** Modern web interfaces often restrict users to copying one response at a time, forcing dozens of manual roundtrips to share context between agents.
2. **Context Drift & Epistemic Blindness:** Agent A (e.g. VS Code Copilot) modifies a UI contract; Agent B (e.g. Antigravity) works on the backend completely unaware of the decision. The operator must remember "who knows what."
3. **Walled Gardens vs. Local Logs:** While local tools write accessible JSONL logs to disk, web interfaces (M365 Copilot, ChatGPT, Gemini Web) remain locked behind closed WebSockets with no unified export flow.

### Core Design Goal
**"Zero-Touch Where Possible, 1-Click Everywhere Else."** Transform DNCP into an ambient conversation fabric and epistemic command center that automatically harvests local chats, seamlessly ingests external exports, tracks agent knowledge states, and enables instant 1-click context handoffs.

---

## 2. Information Architecture (6-Pillar Workbench Integration)

The proposed Workbench GUI (`http://127.0.0.1:8780/`) would integrate the Conversation Mesh across two core views. The sketch is partial: the implemented six-tab navigation still includes Pillar 5 Capability Discovery and Pillar 6 Interaction Lab. Replacing or extending Capability Discovery with the Epistemic Matrix requires an explicit navigation decision; neither existing pillar should be silently removed.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ DNCP WORKBENCH NAVIGATION                                                   │
├──────────────┬──────────────┬──────────────┬─────────────────┬──────────────┤
│ 1. Portfolio │ 2. Queues    │ 3. Fabric    │ 4. Conversation │ 5. Epistemic │
│    & Repos   │    (Backlog) │    Search    │    & Ingestion  │    Matrix    │
└──────────────┴──────────────┴──────────────┴─────────────────┴──────────────┘
```

- **Pillar 4 (Conversations & Universal Ingestion):** Ingestion deck, conversation dialogue stream, search/filter controls, tokenomics KPIs, and granular clipboard copy buttons.
- **Pillar 5 (The Epistemic Matrix & Shared Blackboard):** Visual cross-agent knowledge matrix ("Who Knows What"), active blackboard, and rolling 24h Situational Awareness briefing.

---

## 3. UI/UX Component Specifications

### Component A: Universal Ingestion Deck ("Bring Your Own Chat")

A frictionless onboarding surface supporting drag-and-drop, direct file selection, and clipboard paste for all major platforms.

#### Wireframe: Ingestion Drawer & Drop-Zone
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [▼] ONBOARD / INGEST EXTERNAL CHAT EXPORT                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                     DRAG & DROP EXPORT FILES HERE                      │  │
│  │                                                                        │  │
│  │   Supports: ChatGPT (.json/.zip) • Gemini Takeout • M365 Copilot       │  │
│  │   Claude Web JSON/MD • Perplexity Links • Raw Dialogue Text           │  │
│  │                                                                        │  │
│  │            [Browse Files...]      or     [Paste From Clipboard]        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Auto-Detected Metadata & Mapping:                                           │
│  Platform: [ Auto-Detect: ChatGPT (GPT-4o) ▼ ]   Date: [ 2026-11-01 08:30 ]  │
│  Bind To Repo: [ AIAD-ex12410 (Incubator) ▼ ]   Agent: [ ChatGPT Explorer ]  │
│  Session Title: [ ADR-0015 Implementation Planning                         ] │
│                                                                              │
│  [ Preview 14 Turns ]             [ Ingest & Index into Fabric (1-Click) ]   │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Interaction Flow & Format Auto-Detection:
1. **User Action:** User drags any `.json`, `.zip`, `.md`, or `.txt` file into the drop-zone, or clicks `[Paste From Clipboard]`.
2. **Client-Side Format Sniffer:**
   - Contains `mapping` with `message.content.parts` → **ChatGPT Export** (`conversations.json`).
   - Contains `candidates[].content.parts` or Google Takeout structure → **Google Gemini Chat**.
   - Contains timestamped `[User]` / `[Copilot]` lines or Microsoft Teams/M365 format → **M365 Copilot**.
   - Contains `role: human` / `role: assistant` JSON → **Anthropic Claude**.
3. **Instant Preview Pill:** Displays turn count, detected model badge (e.g. `GPT-4o`, `Claude 3.5 Sonnet`, `Gemini 1.5 Pro`), and estimated tokens.
4. **1-Click Commit (Target):** Persists locally and indexes into SQLite FTS5, then notifies the active session list. Encryption is not implemented; any encryption requirement needs a separate storage/key-management decision.

---

### Component B: Anti-Fatigue Granular Copy Deck

Solves the frustration of manual copy-pasting by providing purpose-built copy buttons with real-time visual feedback.

#### Wireframe: Dialogue Explorer & Action Strip
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ DIALOGUE EXPLORER                                    Filter: [ All Models ▼ ] │
├──────────────────────────────────────────────────────────────────────────────┤
│ SESSION: DEC-0015 Architecture Refinement                                    │
│ Platform: VS Code Copilot  •  Model: Claude 3.5 Sonnet  •  Tokens: 4,820     │
│                                                                              │
│ [ ⚡ 1-Click Copy Full Handoff Packet ]  [ 📦 Export JSON ]  [ 🔍 Raw View ]  │
├──────────────────────────────────────────────────────────────────────────────┤
│ TURN #3 ────────────────────────────────────────────── 2026-11-01 09:12:40   │
│                                                                              │
│ 👤 USER PROMPT:                                [ 📋 Copy Prompt ]            │
│ "How do we ensure the release package has zero external pip dependencies?"  │
│                                                                              │
│ 🤖 ASSISTANT REPLY:               [ 📋 Copy Reply ]  [ 💻 Copy Code Only ]   │
│ "We should use Python's built-in zipfile, hashlib, and urllib modules..."   │
│                                                                              │
│ ```python                                                                    │
│ def build_wheel(src_dir, dist_dir):                                          │
│     # Zero-dependency packaging logic                                        │
│ ```                                                                          │
│                                                                              │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ [ 📑 Copy Entire Turn Pair ]    [ 🚀 Push to Agent Blackboard ]          │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Granular Action Behavior:
- **`[ ⚡ 1-Click Copy Full Handoff Packet ]`**:
  - Automatically compiles:
    1. System Preamble ("You are stepping into an active engineering session...").
    2. Active Repo & Branch Context.
    3. Last *N* turns of dialogue with secret redaction (`TOKEN=***`).
    4. Current goal and verified constraints.
  - Copies directly to system clipboard; UI displays a green checkmark toast: *"Full Handoff Packet Copied (Ready to paste into ChatGPT/Claude/Gemini)"*.
- **`[ 💻 Copy Code Only ]`**:
  - Regex-extracts all markdown fenced code blocks (` ```...``` `).
  - Joins them cleanly with section headers.
  - Allows instant copying of executable code without conversational fluff.
- **`[ 📋 Copy Turn ]` / `[ 📋 Copy Prompt ]` / `[ 📋 Copy Reply ]`**:
  - Single-click isolation of prompt or response.

---

### Component C: The Epistemic Matrix ("Who Knows What")

Eliminates cross-agent context drift by tracking which agent has been briefed on which project, architecture decision, or file lock.

#### Wireframe: Epistemic Matrix UI
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ THE EPISTEMIC MATRIX (CROSS-AGENT KNOWLEDGE TRACKER)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ Legend:  🟢 Synchronized (Current)   🟡 Drifting (Behind)   🔴 Blind (Unaware)│
├──────────────────────────┬──────────────┬──────────────┬──────────────┬──────┤
│ Architecture / Topic     │ Antigravity  │ VS Code Cop. │ ChatGPT Web  │ M365 │
├──────────────────────────┼──────────────┼──────────────┼──────────────┼──────┤
│ DEC-0015 (Zero-Dep Pkg)  │ 🟢 Synced    │ 🟢 Synced    │ 🟡 Drifting  │ 🔴   │
│ DNCP Standalone Repo     │ 🟢 Synced    │ 🟡 Drifting  │ 🔴 Blind     │ 🔴   │
│ Personal-Tracker PWA     │ 🟡 Drifting  │ 🟢 Synced    │ 🔴 Blind     │ 🔴   │
│ InteractionFrame Registry│ 🟢 Synced    │ 🟢 Synced    │ 🟡 Drifting  │ 🔴   │
├──────────────────────────┴──────────────┴──────────────┴──────────────┴──────┤
│                                                                              │
│ ACTION ON SELECTION (ChatGPT Web is Drifting on DEC-0015):                   │
│ [ ⚡ Generate Alignment Briefing for ChatGPT ]   [ 📋 Copy Brief to Clipboard ]│
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Epistemic Matrix Features:
1. **Drift Detection:** If a decision record (e.g. `DEC-0015`) or repository state changes after an agent's last recorded turn, its status transitions to **🟡 Drifting**. If it has never participated in that topic, it is **🔴 Blind**.
2. **1-Click Alignment Briefing:** Clicking `[ Generate Alignment Briefing ]` uses the **Metabolizer Engine** to compute the exact delta between what the agent saw and the current network truth, generating a concise, 1-paragraph briefing for that agent.

---

### Component D: The Shared Blackboard HUD & 24h Situational Digest

A dynamic heads-up display of living network facts.

#### Wireframe: Blackboard & Situational Digest
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ SHARED BLACKBOARD (NETWORK TRUTH & ACTIVE LOCKS)                             │
├──────────────────────────────────────────────────────────────────────────────┤
│ 📌 PINNED TRUTHS:                                                            │
│ • DNCP is a standalone repo at c:\Users\wyand\GitHub-Repos\devnet-control-plane│
│ • ALM (PRJ-0005) is the prompt/skill/eval supplier; all repos consume it.    │
│ • DEC-0015 requires standard library only (no pip install dependencies).     │
│                                                                              │
│ 🔒 ACTIVE WORK & FILE LOCKS:                                                 │
│ • Antigravity: Updating DNCP planning & UI/UX specifications.               │
│ • VS Code Copilot: Idle (Last active in personal-tracker).                   │
│                                                                              │
│ 📰 24-HOUR SITUATIONAL AWARENESS DIGEST:                                     │
│ "Over the last 24 hours, DNCP v0.1.0 was scaffolded, verified, and published │
│ to GitHub (vvaynethomas/devnet-control-plane). The conversation hub was      │
│ expanded with tokenomics and 1-click handoffs. Incubator PR chain #29-#31 is │
│ ready for review."                                                           │
│                                                                              │
│ [ 📋 Copy 24h Digest for Next Agent ]        [ 🔄 Refresh Blackboard ]       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Technical Architecture: Zero-Touch & Low-Touch Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       MULTI-HARNESS INGESTION PIPELINE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   [ Antigravity Logs ] ──(Local Watcher)──┐                                 │
│   [ VS Code Copilot ]  ──(Local Watcher)──┼──► [ Unified SQLite FTS5 Store ]│
│   [ Gemini / Claude ]  ──(Local Gateway)──┤    │                            │
│   [ Web Exports/Zips ] ──(Drop-Zone GUI)──┘    ├──► [ The Metabolizer Agent ]
│                                                │    │  (Facts & Deltas)     │
│                                                │    ▼                       │
│                                                ├──► [ Epistemic Matrix ]    │
│                                                ├──► [ Shared Blackboard ]   │
│                                                └──► [ Granular Copy Engine ]│
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **Local Filesystem Watcher (`DNCP-004`):** Background Python thread monitoring OS file events in `~/.gemini/antigravity/brain` and `%APPDATA%/Code/User/workspaceStorage`. Zero user action required.
2. **In-Line AI Gateway Proxy (`DNCP-007`):** Lightweight `http.server` running on `localhost:8781/v1`. Proxies requests to Gemini/Claude/Perplexity, streaming tokens while logging requests out-of-band.
3. **Universal Drop-Zone (`DNCP-005`):** Browser-based client handling file drops and clipboard pastes with instant format sniffers.
4. **The Metabolizer Background Synthesizer (`DNCP-009`):** Distills dialogue into immutable facts, tracks agent familiarity, and publishes the 24h Situational Digest.

---

## 5. Keyboard Navigation & Quick Commands

| Shortcut | Scope | Action |
| :--- | :--- | :--- |
| `Ctrl + K` | Global | Focus FTS5 search across all harvested conversations and knowledge. |
| `Ctrl + Shift + C` | Dialogue View | Copy Full Handoff Packet for current active conversation. |
| `Ctrl + Shift + X` | Dialogue View | Copy all code blocks in active conversation (Code-Only). |
| `Ctrl + Shift + V` | Ingestion View | Paste raw dialogue or clipboard export into onboarding drawer. |
| `Ctrl + Shift + B` | Epistemic View | Copy 24h Situational Awareness Briefing to clipboard. |

---

## 6. Implementation Roadmap

- **Baseline acceptance (declared v0.1.0):** Resolve CLI/registry distribution blockers and verify the existing granular copy buttons, including all-harness handoffs and feedback (DNCP-001/DNCP-006).
- **Phase 1 (v0.2.0):** Universal Drop-Zone GUI in `control_plane/ui.py` and background watcher for Antigravity & Copilot.
- **Phase 2 (v0.2.0 target):** Local `/v1` AI Gateway Proxy for Gemini API, Anthropic Claude, and Perplexity with zero-touch streaming capture. This follows the root roadmap; no separate v0.2.5 release is committed.
- **Phase 3 (v0.3.0):** Epistemic Matrix visualizer, Shared Blackboard HUD, and Metabolizer synthesis engine with MCP context server support.
