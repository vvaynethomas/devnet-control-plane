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
- **Universal Chat Ingestion Deck:** Drag-and-drop & paste support for:
  - ChatGPT export bundles (`conversations.json`, `.zip`).
  - Google Gemini Chat exports (Google Takeout, web markdown/JSON).
  - Microsoft 365 Copilot (Enterprise transcripts, Purview compliance logs, clipboard dumps).
  - Claude & Perplexity web exports.
- **Background Filesystem Watcher:** Daemon watching `~/.gemini/antigravity/brain` and `%APPDATA%/Code/User/workspaceStorage` for instant, zero-click chat sync.
- **Zero-Touch Local AI Gateway:** OpenAI-compatible loopback proxy (`http://localhost:8781/v1/chat/completions`) routing Gemini API, Anthropic, Perplexity, and OpenAI calls with automated stream logging and token counting.

## v0.3.0 — The Metabolizer & Epistemic Context Mesh (Planned)
- **The Epistemic Matrix ("Who Knows What"):** Visual UI grid mapping agents (Antigravity, Copilot, ChatGPT, Gemini, Human) against projects and architectural decisions, flagging context drift in real time.
- **The Shared Blackboard HUD:** Live bulletin board tracking confirmed decisions, active roadblocks, file locks, and cross-repo dependencies.
- **The "Metabolizer" Agent:** Background synthesizer extracting crystallized facts and generating 24h Situational Awareness Briefing cards.
- **Model Context Protocol (MCP) Server:** Native `devnet-context-server` allowing any MCP-compliant agent (Claude Code, Antigravity, Cursor) to pull situational context without human copy-pasting.

DNCP-011 (local model bridge) and DNCP-012 (ALM consumer exchange) remain unscheduled P3 backlog items; the configurable outbound completion client is only partial evidence for DNCP-011. Versions above are scope targets, not release commitments or acceptance records.
