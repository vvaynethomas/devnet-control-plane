"""Unified Local Loopback Workbench for the Development Network Control Plane (ART-0007)."""

from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from . import DEFAULT_DATA_DIR, DEV_NETWORK_ROOT, FACTORY_ROOT, PACKAGE_VERSION, REGISTRY_PATH
from .capabilities import discover_capabilities
from .decision_aid import DECISION_TOPICS, build_decision_aid
from .fabric import FabricIndex
from .interaction_lab import InteractionFrameEngine
from .portfolio import open_repo_location, scan_portfolio
from .queues import aggregate_queues, match_router_route
from .phone_home import MAX_REQUEST_BYTES, NOTICE, PhoneHome, PhoneHomeError


def _badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="badge badge-{escape(tone)}">{escape(str(text))}</span>'


def _chip_link(eid: str) -> str:
    return f'<a class="chip" href="/?tab=fabric&amp;entity={escape(eid)}">{escape(eid)}</a>'


def _layout(active_tab: str, title: str, body_html: str, flash: str = "") -> str:
    tabs = [
        ("portfolio", "1. Portfolio & Network"),
        ("queues", "2. Queues & Next Actions"),
        ("fabric", "3. Knowledge & Conversation Fabric"),
        ("conversations", "4. Conversations & Tokenomics"),
        ("capabilities", "5. Capability Discovery"),
        ("interaction", "6. Interaction Lab (Frames)"),
    ]
    nav_links = "".join(
        f'<a class="tab-link{" active" if tid == active_tab else ""}" href="/?tab={tid}">{escape(label)}</a>'
        for tid, label in tabs
    )
    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} — Dev Network Control Plane</title>
  <style>
    :root {{
      color-scheme: light dark;
      font: 14px/1.55 "Segoe UI", system-ui, -apple-system, sans-serif;
      --bg: #0f111a;
      --surface: #171a26;
      --surface-2: #1f2334;
      --ink: #eef0f8;
      --muted: #9ba3be;
      --line: #2d334a;
      --accent: #7c6aff;
      --accent-soft: #25204c;
      --good: #3dd68c;
      --good-soft: #133326;
      --warn: #f5b851;
      --warn-soft: #3a2b12;
      --bad: #f26d78;
      --bad-soft: #3b1a20;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #f4f6fb;
        --surface: #ffffff;
        --surface-2: #eef1f8;
        --ink: #1b1e2e;
        --muted: #5a627a;
        --line: #d8deec;
        --accent: #523ee8;
        --accent-soft: #ece9ff;
        --good: #117a48;
        --good-soft: #e3f7ed;
        --warn: #945900;
        --warn-soft: #fff3db;
        --bad: #b42330;
        --bad-soft: #ffe8ea;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .topbar {{
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 16px 28px 0;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .topbar-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .brand h1 {{ margin: 0; font-size: 1.3rem; letter-spacing: -0.02em; }}
    .brand p {{ margin: 2px 0 0; color: var(--muted); font-size: 0.85rem; }}
    .global-search {{ display: flex; gap: 8px; align-items: center; }}
    .global-search input {{
      min-width: 280px;
      padding: 7px 12px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink);
    }}
    .tabs {{ display: flex; gap: 6px; overflow-x: auto; }}
    .tab-link {{
      padding: 9px 14px;
      border-radius: 8px 8px 0 0;
      color: var(--muted);
      font-weight: 600;
      border: 1px solid transparent;
      border-bottom: none;
      white-space: nowrap;
    }}
    .tab-link.active {{
      background: var(--bg);
      color: var(--ink);
      border-color: var(--line);
    }}
    .container {{ max-width: 1420px; margin: 0 auto; padding: 24px 28px 64px; }}
    .stats-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 16px;
    }}
    .stat-label {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .stat-value {{ font-size: 1.55rem; font-weight: 700; margin-top: 2px; }}
    .stat-sub {{ color: var(--muted); font-size: 0.8rem; margin-top: 4px; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 18px 20px;
      margin-bottom: 20px;
    }}
    .panel h2 {{ margin: 0 0 8px; font-size: 1.15rem; }}
    .panel h3 {{ margin: 0 0 6px; font-size: 1rem; }}
    .muted {{ color: var(--muted); }}
    .grid-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }}
    .card {{
      background: var(--surface-2);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 99px;
      font-size: 0.76rem;
      font-weight: 600;
    }}
    .badge-good {{ background: var(--good-soft); color: var(--good); }}
    .badge-warn {{ background: var(--warn-soft); color: var(--warn); }}
    .badge-bad {{ background: var(--bad-soft); color: var(--bad); }}
    .badge-accent {{ background: var(--accent-soft); color: var(--accent); }}
    .badge-neutral {{ background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); }}
    .chip {{
      display: inline-block;
      padding: 2px 7px;
      margin: 1px 3px 1px 0;
      border-radius: 5px;
      background: var(--accent-soft);
      color: var(--accent);
      font-family: Consolas, monospace;
      font-size: 0.78rem;
    }}
    .btn {{
      display: inline-block;
      padding: 6px 12px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink);
      cursor: pointer;
      font-weight: 600;
      font-size: 0.84rem;
    }}
    .btn-primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .btn-sm {{ padding: 3px 8px; font-size: 0.76rem; }}
    input[type="text"], input[type="search"], select, textarea {{
      padding: 8px 10px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink);
      font: inherit;
    }}
    textarea {{ width: 100%; min-height: 95px; resize: vertical; }}
    pre {{
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      white-space: pre-wrap;
      font-family: Consolas, ui-monospace, monospace;
      font-size: 0.83rem;
    }}
    mark {{ background: var(--warn-soft); color: var(--warn); padding: 0 3px; border-radius: 3px; }}
    .flash {{
      background: var(--good-soft);
      color: var(--good);
      border: 1px solid var(--good);
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-weight: 600;
    }}
    .inline-form {{ display: inline-block; margin: 0 3px 0 0; }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-head">
      <div class="brand">
        <h1>Development Network Control Plane <span class="badge badge-accent">ART-0007 · v{escape(PACKAGE_VERSION)}</span></h1>
        <p>Nervous system across repositories, product queues, knowledge &amp; AI conversations, reusable capabilities, and InteractionFrame evaluations</p>
      </div>
      <form class="global-search" method="get" action="/">
        <input type="hidden" name="tab" value="fabric">
        <input type="search" name="q" placeholder="Search knowledge, chats, IDs, patterns…" aria-label="Global Fabric Search">
        <button type="submit" class="btn btn-primary">Search Fabric</button>
      </form>
    </div>
    <nav class="tabs" aria-label="Control Plane Pillars">{nav_links}</nav>
  </header>
  <main class="container">
    {flash_html}
    {body_html}
  </main>
</body>
</html>"""


class ControlPlaneWorkbench:
    """Stateful service container for the 5 Control Plane pillars."""

    def __init__(
        self,
        factory_root: Path = FACTORY_ROOT,
        network_root: Path = DEV_NETWORK_ROOT,
        data_dir: Path = DEFAULT_DATA_DIR,
        registry_path: Path = REGISTRY_PATH,
    ) -> None:
        self.factory_root = factory_root
        self.network_root = network_root
        self.data_dir = data_dir
        self.phone_home = PhoneHome(factory_root, network_root, data_dir)
        self.phone_home_csrf = secrets.token_urlsafe(32)
        self.fabric = FabricIndex(db_path=data_dir / "control_plane_fabric.sqlite", factory_root=factory_root)
        self.interaction_lab = InteractionFrameEngine(
            registry_path=registry_path,
            db_path=data_dir / "interaction_lab.sqlite",
        )
        from .conversations import UnifiedConversationHub
        self.conversations_hub = UnifiedConversationHub(data_dir=data_dir, factory_root=factory_root)

    def render_portfolio_tab(self, include_worktrees: bool = False) -> str:
        data = scan_portfolio(self.network_root, self.factory_root, include_worktrees=include_worktrees)
        s = data["summary"]
        stats = f"""
        <div class="stats-row">
          <div class="stat-card"><div class="stat-label">Known Repositories</div><div class="stat-value">{s['total_repos']}</div><div class="stat-sub">In {escape(data['network_root'])}</div></div>
          <div class="stat-card"><div class="stat-label">Clean Git Trees</div><div class="stat-value">{s['clean_repos']}</div><div class="stat-sub">Zero uncommitted changes</div></div>
          <div class="stat-card"><div class="stat-label">Active / Modified Trees</div><div class="stat-value">{s['dirty_repos']}</div><div class="stat-sub">Staged, modified, or untracked</div></div>
          <div class="stat-card"><div class="stat-label">SRC-0013 Audited</div><div class="stat-value">{s['audited_repos']}</div><div class="stat-sub">Linked to preservation baseline</div></div>
          <div class="stat-card"><div class="stat-label">Incubated Projects</div><div class="stat-value">{s['incubated_projects']}</div><div class="stat-sub">PRJ-0001 through PRJ-0005</div></div>
        </div>
        """

        prj_cards = []
        for p in data["incubated_projects"]:
            up_chips = "".join(_chip_link(u) for u in p.get("upstream_refs", []))
            down_chips = "".join(_chip_link(d) for d in p.get("downstream_refs", []))
            q_link = (
                f'<a class="btn btn-sm" href="/?tab=queues&amp;owner={escape(p["id"])}">View Queue</a>'
                if p.get("has_local_backlog")
                else ""
            )
            open_btn = ""
            if p.get("abs_path"):
                open_btn = f"""
                <form class="inline-form" method="post" action="/action/open-repo">
                  <input type="hidden" name="path" value="{escape(p['abs_path'])}">
                  <input type="hidden" name="mode" value="explorer">
                  <button type="submit" class="btn btn-sm">Open Folder</button>
                </form>"""
            prj_cards.append(
                f"""
                <div class="card">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                    <strong>{_chip_link(p['id'])} {escape(p['title'])}</strong>
                    {_badge(p.get('workshop', 'WS'), 'accent')}
                  </div>
                  <p class="muted" style="font-size:0.84rem;margin:4px 0 10px;">{escape(p.get('scope', '')[:220])}</p>
                  <div style="margin-bottom:8px;">
                    <span class="muted" style="font-size:0.78rem;">Upstream:</span> {up_chips or '—'}
                    <span class="muted" style="font-size:0.78rem;margin-left:8px;">Downstream:</span> {down_chips or '—'}
                  </div>
                  <div>{q_link} {open_btn}</div>
                </div>
                """
            )

        repo_rows = []
        for r in data["repositories"]:
            g = r["git"]
            st = r["stewardship"]
            aud = r["audit"]
            state_tone = "good" if g["state_label"] == "clean" else ("warn" if g["is_git"] else "neutral")
            stew_tone = "accent" if st["stewardship_tier"] in ("factory-governed", "independent-kit") else "neutral"
            audit_html = (
                f'{_chip_link("SRC-0013")} <span class="muted">{escape(aud["visibility"])} · {escape(aud["audit_summary"][:95])}</span>'
                if aud
                else '<span class="muted">Not in SRC-0013 snapshot</span>'
            )
            readme_inspect = (
                f'<a class="btn btn-sm" href="/?tab=portfolio&amp;inspect={escape(r["readme_path"])}#inspector">Read README</a>'
                if r.get("readme_path")
                else ""
            )
            repo_rows.append(
                f"""
                <tr>
                  <td>
                    <strong>{escape(r['name'])}</strong>
                    {" " + _badge("Incubator Host", "accent") if r["is_factory"] else ""}
                    <div class="muted" style="font-size:0.76rem;font-family:Consolas,monospace;">{escape(r['path'])}</div>
                  </td>
                  <td><code>{escape(g['branch'])}</code><div class="muted" style="font-size:0.76rem;"><code>{escape(g['head_short'])}</code></div></td>
                  <td>{_badge(g['state_label'], state_tone)}</td>
                  <td>
                    <div>{escape(g['last_commit_date'])}</div>
                    <div class="muted" style="font-size:0.78rem;">{escape(g['last_commit_subject'][:65])}</div>
                  </td>
                  <td>
                    {_badge(st['stewardship_tier'], stew_tone)}
                    <div class="muted" style="font-size:0.76rem;">{escape(st['role'])}</div>
                  </td>
                  <td>{audit_html}</td>
                  <td style="white-space:nowrap;">
                    <form class="inline-form" method="post" action="/action/open-repo">
                      <input type="hidden" name="path" value="{escape(r['path'])}">
                      <input type="hidden" name="mode" value="vscode">
                      <button type="submit" class="btn btn-sm btn-primary">VS Code</button>
                    </form>
                    <form class="inline-form" method="post" action="/action/open-repo">
                      <input type="hidden" name="path" value="{escape(r['path'])}">
                      <input type="hidden" name="mode" value="explorer">
                      <button type="submit" class="btn btn-sm">Explorer</button>
                    </form>
                    {readme_inspect}
                  </td>
                </tr>
                """
            )

        return f"""
        {stats}
        <section class="panel">
          <h2>Incubated Projects &amp; Product Boundaries (DEC-0001 / DEC-0008 / DEC-0011)</h2>
          <p class="muted">Authoritative project records registered in the incubator with direct links to their local queues and provenance.</p>
          <div class="grid-3">{''.join(prj_cards)}</div>
        </section>
        <section class="panel">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
              <h2>Development Network Repositories ({len(repo_rows)})</h2>
              <p class="muted">Live Git status, active branch, last commit, stewardship state, and SRC-0013 rehabilitation audit notes.</p>
            </div>
            <div>
              <a class="btn btn-sm" href="/?tab=portfolio&amp;worktrees={'0' if include_worktrees else '1'}">
                {'Hide Worktree Containers' if include_worktrees else 'Show Worktree Containers'}
              </a>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Branch / HEAD</th>
                <th>Git Status</th>
                <th>Last Activity</th>
                <th>Stewardship</th>
                <th>Audit Provenance</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>{''.join(repo_rows)}</tbody>
          </table>
        </section>
        """

    def render_queues_tab(self, owner_filter: str = "", bucket_filter: str = "", route_query: str = "") -> str:
        qdata = aggregate_queues(self.factory_root, self.network_root)
        s = qdata["summary"]
        route_match = match_router_route(route_query) if route_query else None

        stats = f"""
        <div class="stats-row">
          <div class="stat-card"><div class="stat-label">Active Queue Items</div><div class="stat-value">{s['active_non_pointer_rows']}</div><div class="stat-sub">Across Factory + PRJ queues</div></div>
          <div class="stat-card"><div class="stat-label">Awaiting Acceptance</div><div class="stat-value" style="color:var(--warn);">{s['awaiting_acceptance']}</div><div class="stat-sub">Ready for human sign-off</div></div>
          <div class="stat-card"><div class="stat-label">Blocked / Gate Pending</div><div class="stat-value" style="color:var(--bad);">{s['blocked']}</div><div class="stat-sub">Waiting on ADR or policy gate</div></div>
          <div class="stat-card"><div class="stat-label">Open / Ready</div><div class="stat-value" style="color:var(--accent);">{s['open']}</div><div class="stat-sub">Available for execution</div></div>
          <div class="stat-card"><div class="stat-label">Accepted (Done)</div><div class="stat-value" style="color:var(--good);">{s['done']}</div><div class="stat-sub">Operator accepted</div></div>
        </div>
        """

        next_cards = []
        for na in qdata["next_actions"][:9]:
            tone = "warn" if na["badge"] == "awaiting-acceptance" else "accent"
            next_cards.append(
                f"""
                <div class="card">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <strong><code>{escape(na['id'])}</code> · {escape(na['owner'])}</strong>
                    {_badge(na['kind'], tone)}
                  </div>
                  <div style="font-weight:600;margin-bottom:4px;">{escape(na['title'][:95])}</div>
                  <div class="muted" style="font-size:0.8rem;margin-bottom:6px;">{escape(na['reason'][:140])}</div>
                  <div style="font-size:0.78rem;">
                    <code>{escape(na['source_path'])}#L{na['line']}</code>
                  </div>
                </div>
                """
            )

        route_match_html = ""
        if route_match:
            if route_match["matched"] and route_match["route"]:
                rt = route_match["route"]
                route_match_html = f"""
                <div class="card" style="margin-bottom:12px;border-color:var(--good);">
                  <strong>Recommended Route for "{escape(route_query)}":</strong>
                  {_chip_link(rt['entity_id'])} — {escape(rt['procedure'])}
                  (<code>{escape(rt['path'])}</code>)
                </div>
                """
            else:
                route_match_html = f"""
                <div class="card" style="margin-bottom:12px;border-color:var(--warn);">
                  <strong>No exact route match:</strong> {escape(route_match.get('message', ''))}
                </div>
                """

        router_rows = "".join(
            f"""
            <tr>
              <td>{escape(r['input_type'])}</td>
              <td>{_chip_link(r['entity_id'])}</td>
              <td>{escape(r['procedure'])}</td>
              <td><code>{escape(r['path'])}</code></td>
            </tr>
            """
            for r in qdata["router_routes"]
        )

        items = [i for i in qdata["all_items"] if not i["is_pointer"]]
        if owner_filter:
            items = [i for i in items if i["owner_id"] == owner_filter]
        if bucket_filter:
            items = [i for i in items if i["bucket"] == bucket_filter]

        bucket_tones = {
            "awaiting_acceptance": "warn",
            "blocked": "bad",
            "open": "accent",
            "done": "good",
        }
        rows_html = []
        for item in items:
            refs = "".join(_chip_link(rid) for rid in item["referenced_ids"][:6])
            rows_html.append(
                f"""
                <tr>
                  <td><strong><code>{escape(item['id'])}</code></strong><div class="muted" style="font-size:0.75rem;">{escape(item['priority'])}</div></td>
                  <td>{_badge(item['owner_id'], 'neutral')}</td>
                  <td>
                    <strong>{escape(item['title'])}</strong>
                    <div class="muted" style="font-size:0.8rem;margin-top:3px;">{escape(item['criteria'][:220])}</div>
                    <div style="margin-top:4px;">{refs}</div>
                  </td>
                  <td><span class="muted" style="font-size:0.82rem;">{escape(item['depends_on'])}</span></td>
                  <td>
                    {_badge(item['bucket'].replace('_', ' '), bucket_tones.get(item['bucket'], 'neutral'))}
                    <div class="muted" style="font-size:0.76rem;margin-top:3px;">{escape(item['status_raw'][:110])}</div>
                  </td>
                  <td>
                    <a class="btn btn-sm" href="/?tab=queues&amp;inspect={escape(item['abs_path'])}#inspector">
                      {escape(item['source_path'])}:{item['line']}
                    </a>
                  </td>
                </tr>
                """
            )

        return f"""
        {stats}
        <section class="panel">
          <h2>High-Leverage Next Actions &amp; Human Gates</h2>
          <p class="muted">Surfaces items awaiting operator acceptance first, followed by ready P1 and PRJ-0005 work slices.</p>
          <div class="grid-3">{''.join(next_cards)}</div>
        </section>

        <section class="panel">
          <h2>Data-Driven Next-Action Router (PAT-0001 / BL-0014)</h2>
          <form method="get" action="/" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
            <input type="hidden" name="tab" value="queues">
            <input type="text" name="route_q" value="{escape(route_query)}" placeholder="Describe what you have (e.g. 'chat transcript', 'paper', 'InteractionFrame eval', 'ADR')…" style="flex:1;min-width:280px;">
            <button type="submit" class="btn btn-primary">Route Input</button>
          </form>
          {route_match_html}
          <table>
            <thead><tr><th>Operator Input Type</th><th>Target Entity</th><th>Canonical Procedure</th><th>Artifact Path</th></tr></thead>
            <tbody>{router_rows}</tbody>
          </table>
        </section>

        <section class="panel">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:12px;">
            <div>
              <h2>Aggregated Network Queues ({len(rows_html)} items shown)</h2>
              <p class="muted">Authoritative tasks across Factory BACKLOG.md, PRJ-0002, PRJ-0004, PRJ-0005, and standalone product repos (historical pointers hidden).</p>
            </div>
            <form method="get" action="/" style="display:flex;gap:8px;align-items:center;">
              <input type="hidden" name="tab" value="queues">
              <select name="owner">
                <option value="">All Owners</option>
                <option value="FACTORY" {"selected" if owner_filter == "FACTORY" else ""}>FACTORY</option>
                <option value="PRJ-0002" {"selected" if owner_filter == "PRJ-0002" else ""}>PRJ-0002 (Learning)</option>
                <option value="PRJ-0004" {"selected" if owner_filter == "PRJ-0004" else ""}>PRJ-0004 (Tracker)</option>
                <option value="PRJ-0005" {"selected" if owner_filter == "PRJ-0005" else ""}>PRJ-0005 (ALM)</option>
                <option value="PRJ-0001-EXT" {"selected" if owner_filter == "PRJ-0001-EXT" else ""}>PRJ-0001 (Catalog Repo)</option>
              </select>
              <select name="bucket">
                <option value="">All Status Buckets</option>
                <option value="awaiting_acceptance" {"selected" if bucket_filter == "awaiting_acceptance" else ""}>Awaiting Acceptance</option>
                <option value="blocked" {"selected" if bucket_filter == "blocked" else ""}>Blocked</option>
                <option value="open" {"selected" if bucket_filter == "open" else ""}>Open / Ready</option>
                <option value="done" {"selected" if bucket_filter == "done" else ""}>Done</option>
              </select>
              <button type="submit" class="btn">Filter</button>
              <a class="btn" href="/?tab=queues">Reset</a>
            </form>
          </div>
          <table>
            <thead>
              <tr><th>ID / Priority</th><th>Owner</th><th>Task &amp; Criteria</th><th>Depends On</th><th>Status</th><th>Source Artifact</th></tr>
            </thead>
            <tbody>{''.join(rows_html)}</tbody>
          </table>
        </section>
        """

    def render_fabric_tab(self, query: str = "", kind_filter: str = "", entity_id: str = "") -> str:
        search_data = self.fabric.search(query=query, kind_filter=kind_filter, limit=45)
        counts = search_data["counts"]

        entity_panel = ""
        if entity_id:
            ent = self.fabric.get_entity(entity_id)
            if ent:
                up_links = "".join(
                    f'<div style="margin:3px 0;">{_chip_link(u["id"])} <span>{escape(u["title"])}</span> <span class="muted">({escape(u["kind"])})</span></div>'
                    for u in ent.get("upstream_nodes", [])
                ) or '<div class="muted">None (root source or top-level entity)</div>'
                down_links = "".join(
                    f'<div style="margin:3px 0;">{_chip_link(d["id"])} <span>{escape(d["title"])}</span> <span class="muted">({escape(d["kind"])})</span></div>'
                    for d in ent.get("downstream_nodes", [])
                ) or '<div class="muted">No downstream dependents recorded yet</div>'
                conv_links = "".join(
                    f'<div style="margin:3px 0;">{_chip_link(c["id"])} <span>{escape(c["title"])}</span> <span class="muted">({escape(c["harness"])})</span></div>'
                    for c in ent.get("related_conversations", [])
                ) or '<div class="muted">No indexed AI conversations mention this ID yet</div>'
                entity_panel = f"""
                <section class="panel" style="border-color:var(--accent);">
                  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
                    <h2>Provenance &amp; Entity Inspector: <code>{escape(ent['id'])}</code> — {escape(ent['title'])}</h2>
                    <div>{_badge(ent['kind'], 'accent')} {_badge(ent['status'], 'neutral')}</div>
                  </div>
                  <p class="muted">Path: <code>{escape(ent['path'])}</code> · Date: {escape(ent['created_date'] or '—')}</p>
                  <div class="grid-3" style="margin-bottom:14px;">
                    <div class="card"><h3>Upstream Provenance (Derived From)</h3>{up_links}</div>
                    <div class="card"><h3>Downstream Impact (Produces)</h3>{down_links}</div>
                    <div class="card"><h3>Mentioned in AI Conversations</h3>{conv_links}</div>
                  </div>
                  <details open>
                    <summary style="cursor:pointer;font-weight:600;margin-bottom:8px;">Full Content / Redacted Transcript Excerpt</summary>
                    <pre>{escape(ent.get('body', '')[:6000])}</pre>
                  </details>
                </section>
                """

        stat_cards = "".join(
            f'<a class="stat-card" href="/?tab=fabric&amp;kind={escape(k)}&amp;q={escape(query)}"><div class="stat-label">{escape(k)}</div><div class="stat-value">{v}</div><div class="stat-sub">Click to filter</div></a>'
            for k, v in counts.items()
        )

        result_rows = []
        for r in search_data["results"]:
            up_chips = "".join(_chip_link(u) for u in r["upstream_refs"][:5])
            down_chips = "".join(_chip_link(d) for d in r["downstream_refs"][:5])
            snippet_html = r["snippet"] if "<mark>" in r["snippet"] else escape(r["snippet"])
            result_rows.append(
                f"""
                <tr>
                  <td style="white-space:nowrap;">
                    <strong>{_chip_link(r['id'])}</strong>
                    <div style="margin-top:4px;">{_badge(r['kind'], 'accent' if r['kind'] != 'conversation' else 'good')}</div>
                  </td>
                  <td>
                    <a href="/?tab=fabric&amp;entity={escape(r['id'])}&amp;q={escape(query)}&amp;kind={escape(kind_filter)}"><strong>{escape(r['title'])}</strong></a>
                    <div class="muted" style="font-size:0.83rem;margin-top:4px;">{snippet_html}</div>
                    <div class="muted" style="font-size:0.75rem;margin-top:4px;"><code>{escape(r['path'])}</code> · {escape(r['created_date'])}</div>
                  </td>
                  <td>{up_chips or '<span class="muted">—</span>'}</td>
                  <td>{down_chips or '<span class="muted">—</span>'}</td>
                </tr>
                """
            )

        from control_plane.handoff import discover_antigravity_sessions, compile_context_handoff
        sessions = discover_antigravity_sessions(max_sessions=8)
        current_handoff = compile_context_handoff(turns_limit=5, factory_root=self.factory_root, network_root=self.network_root)
        handoff_md = current_handoff.get("markdown", "")
        handoff_sess_id = current_handoff.get("session_id", "latest")

        handoff_section = f"""
        <section id="handoff" class="panel" style="border: 2px solid var(--accent); background: rgba(31, 111, 235, 0.05); margin-bottom: 24px;">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
            <div>
              <h2 style="margin:0 0 4px 0;">Cross-Session Context Handoff &amp; Sync ("Who Said What &amp; Where We Are")</h2>
              <p class="muted" style="margin:0;">Stops turn-by-turn copy-pasting across AI interfaces. Compiles active dialogue, git diffs, ADR refs, and open gates into a single ready-to-paste markdown packet.</p>
            </div>
            <div style="display:flex; gap:8px;">
              <button id="copy-handoff-btn" class="btn btn-primary" type="button" onclick="copyHandoffPacket()">
                1-Click Copy Full Handoff Packet
              </button>
            </div>
          </div>

          <div style="margin-bottom:10px; display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
            <div><strong>Active Session:</strong> <code>{escape(handoff_sess_id[:16])}…</code></div>
            <div><strong>Turns Included:</strong> {current_handoff.get('included_turns', 0)} of {current_handoff.get('total_turns', 0)}</div>
            <div><strong>Git State:</strong> <code>{escape(current_handoff.get('git_state', {}).get('branch', 'main'))} @ {escape(current_handoff.get('git_state', {}).get('commit', 'head'))}</code></div>
          </div>

          <textarea id="handoff-textarea" readonly style="width:100%; height:200px; font-family:monospace; font-size:0.82rem; background:#0d1117; color:#c9d1d9; border:1px solid #30363d; border-radius:6px; padding:10px; resize:vertical; box-sizing:border-box;">{escape(handoff_md)}</textarea>

          <script>
            function copyHandoffPacket() {{
              const ta = document.getElementById('handoff-textarea');
              ta.select();
              navigator.clipboard.writeText(ta.value).then(() => {{
                const btn = document.getElementById('copy-handoff-btn');
                const orig = btn.innerText;
                btn.innerText = '✓ Copied Context Packet to Clipboard!';
                btn.style.background = '#238636';
                setTimeout(() => {{
                  btn.innerText = orig;
                  btn.style.background = '';
                }}, 3000);
              }}).catch(err => {{
                alert('Select all and copy from the text box directly: ' + err);
              }});
            }}
          </script>
        </section>
        """

        return f"""
        <div class="stats-row">{stat_cards}</div>
        {handoff_section}
        {entity_panel}
        <section class="panel">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:14px;">
            <div>
              <h2>Knowledge &amp; Conversation Fabric (SQLite FTS5)</h2>
              <p class="muted">Single search box across Sources (SRC), Findings (FND), Patterns (PAT), Decisions (DEC), Artifacts (ART), Skills (SKL), and local AI conversations.</p>
            </div>
            <form method="post" action="/action/rebuild-fabric">
              <button type="submit" class="btn">Re-Harvest &amp; Rebuild FTS5 Index</button>
            </form>
          </div>
          <form method="get" action="/" style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;">
            <input type="hidden" name="tab" value="fabric">
            <input type="search" name="q" value="{escape(query)}" placeholder="Search across all findings, decisions, sources, and AI chats…" style="flex:1;min-width:280px;">
            <select name="kind">
              <option value="">All Entity Kinds</option>
              {''.join(f'<option value="{escape(k)}" {"selected" if kind_filter == k else ""}>{escape(k)} ({v})</option>' for k, v in counts.items())}
            </select>
            <button type="submit" class="btn btn-primary">Search</button>
            <a class="btn" href="/?tab=fabric">Clear</a>
          </form>
          <table>
            <thead>
              <tr><th>ID / Kind</th><th>Title, Matched Excerpt &amp; Location</th><th>Upstream Refs</th><th>Downstream Refs</th></tr>
            </thead>
            <tbody>{''.join(result_rows)}</tbody>
          </table>
        </section>
        """

    def render_decision_aid(
        self, topic: str = "infrastructure-decision", operator_context: str = "",
        problem_query: str = "",
    ) -> str:
        options = "".join(
            f'<option value="{escape(key)}" {"selected" if key == topic else ""}>'
            f'{escape(value["title"])}</option>'
            for key, value in DECISION_TOPICS.items()
        )
        form = f"""
        <section class="panel">
          <h2>Decision Aid — Review Before Committing</h2>
          <p class="muted">Read-only guidance from tagged canonical incubator records, not a provider selector or optimizer.</p>
          <form method="get" action="/">
            <input type="hidden" name="tab" value="capabilities">
            <input type="hidden" name="prob" value="{escape(problem_query)}">
            <label for="aid-topic">Decision topic</label>
            <select id="aid-topic" name="aid_topic">{options}</select>
            <label for="aid-context">Operator context &amp; constraints (unverified)</label>
            <textarea id="aid-context" name="aid_context" style="width:100%;height:80px;"
              placeholder="Project, required affordances, context/access evidence, operational constraints, alternatives…">{escape(operator_context)}</textarea>
            <p class="muted">Do not enter secrets. Inputs are not persisted by DNCP, but GET URLs may appear in browser history.</p>
            <button type="submit" class="btn">Review Canonical Guidance</button>
          </form>
        """
        try:
            aid = build_decision_aid(self.factory_root, topic, operator_context)
        except (OSError, ValueError) as exc:
            return form + f'<p role="alert">Decision aid unavailable: {escape(str(exc))}</p></section>'
        questions = "".join(f"<li>{escape(question)}</li>" for question in aid["questions"])
        alternatives = "".join(f"<li>{escape(option)}</li>" for option in aid["alternatives"])
        cards = []
        for record in aid["records"]:
            references = "".join(
                f'<li>{_chip_link(ref["id"]) if ref["resolved"] else escape(ref["id"])} '
                f'— {escape(ref["title"])} ({escape(ref["status"])})</li>'
                for ref in record["upstream_refs"]
            ) or "<li>No upstream provenance recorded; verify the source before relying on this guidance.</li>"
            cards.append(f"""
            <div class="card">
              <strong>{_chip_link(record['id'])} {escape(record['title'])}</strong>
              {_badge(record['status'], 'neutral')} {_badge(record['kind'], 'neutral')}
              <p class="muted">Canonical path: <code>{escape(record['path'])}</code><br>
                Record date (not freshness verification): {escape(record['created_date'] or 'unknown')}</p>
              <details><summary>Read canonical guidance &amp; alternatives</summary>
                <pre style="white-space:pre-wrap;overflow-wrap:anywhere;">{escape(record['body'])}</pre>
              </details>
              <details><summary>Upstream source &amp; provenance</summary><ul>{references}</ul></details>
            </div>
            """)
        empty = (
            '<p role="status">No canonical records with the selected topic tag were found. '
            'Register provisional records in the incubator; no recommendation can be inferred from absence.</p>'
        )
        context = (
            f'<p><strong>Your context (not verified):</strong> {escape(aid["operator_context"])}</p>'
            if aid["operator_context"] else
            '<p class="muted">No project constraints supplied; this is general guidance, not a project-specific recommendation.</p>'
        )
        return form + f"""
          {context}
          <p class="muted">{escape(aid['uncertainty'])}</p>
          <div class="grid-2">
            <div><h3>Questions to resolve</h3><ul>{questions}</ul></div>
            <div><h3>Alternatives to compare (not ranked)</h3><ul>{alternatives}</ul></div>
          </div>
          <p class="muted">Topic tags select records, not readiness. Records are read from the incubator now;
            rebuild Fabric after canonical changes to refresh its linked entity inspector.</p>
          {''.join(cards) or empty}
        </section>
        """

    def render_capabilities_tab(
        self, problem_query: str = "", aid_topic: str = "infrastructure-decision",
        aid_context: str = "",
    ) -> str:
        if not self.fabric.freshness()["built"]:
            self.fabric.rebuild(include_conversations=False)
        cap = discover_capabilities(problem_query, self.factory_root, self.fabric)
        s = cap["summary"]

        solved_cards = []
        for item in cap["have_we_solved_this_before"][:6]:
            solved_cards.append(
                f"""
                <div class="card">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    {_chip_link(item['id'])}
                    {_badge(item['kind'], 'accent')}
                  </div>
                  <strong>{escape(item['title'])}</strong>
                  <p class="muted" style="font-size:0.82rem;margin:6px 0;">{escape(re_strip_marks(item['snippet'])[:180])}</p>
                  <div class="muted" style="font-size:0.75rem;"><code>{escape(item['path'])}</code></div>
                </div>
                """
            )

        pattern_cards = []
        for pat in cap["related_patterns"]:
            pattern_cards.append(
                f"""
                <div class="card">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    {_chip_link(pat['id'])}
                    {_badge('Reusable Pattern', 'good')}
                  </div>
                  <strong>{escape(pat['title'])}</strong>
                  <p class="muted" style="font-size:0.82rem;margin:6px 0;">{escape(pat['summary'][:200])}</p>
                  <div class="muted" style="font-size:0.75rem;"><code>{escape(pat['path'])}</code></div>
                </div>
                """
            )

        tool_rows = []
        for t in cap["existing_tools_and_modules"]:
            id_html = _chip_link(t["id"]) if not t["id"].startswith("MOD:") else f'<code>{escape(t["id"])}</code>'
            syms = ", ".join(f"<code>{escape(sym)}</code>" for sym in t.get("symbols", [])[:6])
            tool_rows.append(
                f"""
                <tr>
                  <td>{id_html}<div>{_badge(t['category'], 'neutral')}</div></td>
                  <td><strong>{escape(t['title'])}</strong><div class="muted" style="font-size:0.8rem;">{escape(t['summary'])}</div></td>
                  <td>{syms or '<span class="muted">—</span>'}</td>
                  <td><code>{escape(t['path'])}</code></td>
                </tr>
                """
            )

        return f"""
        {self.render_decision_aid(aid_topic, aid_context, problem_query)}
        {self.render_phone_home(problem_query)}
        <div class="stats-row">
          <div class="stat-card"><div class="stat-label">Cataloged Capabilities</div><div class="stat-value">{s['total_cataloged_capabilities']}</div><div class="stat-sub">Skills, Runbooks, Patterns, Python Modules</div></div>
          <div class="stat-card"><div class="stat-label">Matching Tools &amp; Modules</div><div class="stat-value">{s['matching_tools_and_modules']}</div><div class="stat-sub">Exploit before building</div></div>
          <div class="stat-card"><div class="stat-label">Matching Patterns</div><div class="stat-value">{s['matching_patterns']}</div><div class="stat-sub">PAT-0001 through PAT-0004</div></div>
          <div class="stat-card"><div class="stat-label">Prior Findings &amp; Chats</div><div class="stat-value">{s['prior_solutions_and_findings']}</div><div class="stat-sub">Solved problems &amp; decisions</div></div>
        </div>

        <section class="panel">
          <h2>Capability Discovery — "What Should I Exploit Instead of Rebuilding?"</h2>
          <p class="muted">Describe a problem or capability (e.g., <code>sqlite search</code>, <code>rclone cloud</code>, <code>stewardship</code>, <code>duplicate hash</code>, <code>interaction frame</code>) to discover existing tools, modules, patterns, and prior findings.</p>
          <form method="get" action="/" style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">
            <input type="hidden" name="tab" value="capabilities">
            <input type="hidden" name="aid_topic" value="{escape(aid_topic)}">
            <input type="hidden" name="aid_context" value="{escape(aid_context)}">
            <input type="search" name="prob" value="{escape(problem_query)}" placeholder="Describe your problem or needed capability…" style="flex:1;min-width:300px;">
            <button type="submit" class="btn btn-primary">Discover Existing Leverage</button>
            <a class="btn" href="/?tab=capabilities&amp;prob=sqlite+fts5+index">Try: SQLite Index</a>
            <a class="btn" href="/?tab=capabilities&amp;prob=stewardship+handover">Try: Stewardship</a>
            <a class="btn" href="/?tab=capabilities&amp;prob=interaction+frame">Try: Interaction Frame</a>
          </form>
        </section>

        <div class="grid-2">
          <section class="panel">
            <h2>1. "Have We Solved This Before?" (Findings, ADRs &amp; Chats)</h2>
            <div class="grid-2">{''.join(solved_cards) or '<p class="muted">Enter a problem query above to search prior findings and conversations.</p>'}</div>
          </section>
          <section class="panel">
            <h2>2. "What Patterns Are Related?" (PAT-####)</h2>
            <div class="grid-2">{''.join(pattern_cards) or '<p class="muted">No matching patterns.</p>'}</div>
          </section>
        </div>

        <section class="panel">
          <h2>3. "Do We Already Have a Tool or Code Module for This?" ({len(tool_rows)} matches)</h2>
          <table>
            <thead><tr><th>ID / Type</th><th>Capability &amp; Interface</th><th>Exported Symbols / Refs</th><th>Repository Path</th></tr></thead>
            <tbody>{''.join(tool_rows)}</tbody>
          </table>
        </section>
        """

    def render_phone_home(self, query: str = "") -> str:
        try:
            data = self.phone_home.check(query) if query.strip() else None
            inbox = self.phone_home.list(limit=10)
        except (PhoneHomeError, OSError, sqlite3.Error) as exc:
            return f'<section class="panel"><h2>Network phone-home unavailable</h2><p>{escape(str(exc))}</p></section>'
        result = f"<pre>{escape(json.dumps(data, indent=2, ensure_ascii=False))}</pre>" if data else ""
        entries = "".join(
            f'<li>{escape(item["title"])} (provisional) '
            f'<a href="/api/phone-home/submissions?id={escape(item["id"])}">Review / JSON export</a></li>'
            for item in inbox["submissions"]
        )
        options = "".join(f'<option value="{kind}">{kind}</option>' for kind in
                          ("discovery", "tool", "skill", "runbook", "module", "finding", "decision"))
        return f"""
        <section class="panel">
          <h2>Network phone-home: check before building</h2>
          <p>Order: existing network capability (reuse/customize), battle-tested external component,
          existing-product extension, then justified standalone product. Stop at sufficient evidence;
          unknown checks remain unresolved. You make the final choice; nothing is dispatched.</p>
          <p>{escape(NOTICE)} Do not submit secrets or sensitive material. Local storage is not encrypted.</p>
          <p>CLI: <code>devnet phone-home check "your need"</code>; API: <code>/api/phone-home/check?q=your+need</code>; MCP: <code>devnet mcp</code>.</p>
          <form method="get" action="/">
            <input type="hidden" name="tab" value="capabilities">
            <input name="prob" maxlength="2000" required value="{escape(query)}" placeholder="What can we reuse?">
            <button type="submit" class="btn">Check network library</button>
          </form>
          {result}
          <h3>Report a discovery or reusable tool</h3>
          <form method="post" action="/action/phone-home-submit" style="display:grid;gap:8px;">
            <input type="hidden" name="csrf" value="{escape(self.phone_home_csrf)}">
            <label>Kind <select name="kind">{options}</select></label>
            <label>Title <input name="title" maxlength="200" required></label>
            <label>Summary <textarea name="summary" maxlength="20000" required></textarea></label>
            <label>Source repository <input name="source_repo" maxlength="1000" required></label>
            <label>Reuse-check query (unverified) <input name="reuse_query" maxlength="2000" required value="{escape(query)}"></label>
            <label>Session reference <input name="source_session" maxlength="1000"></label>
            <label>Evidence path, URL or commit (not fetched) <input name="source_ref" maxlength="1000"></label>
            <label>External component evidence (unverified; no live lookup) <textarea name="external_evidence" maxlength="20000"></textarea></label>
            <label>Related IDs, comma-separated <input name="related_refs"></label>
            <label>Tags, comma-separated <input name="tags"></label>
            <button type="submit" class="btn btn-primary">Submit provisional intake</button>
          </form>
          <h3>Local provisional inbox ({inbox["total"]} total)</h3>
          <ul>{entries or '<li>No provisional submissions yet.</li>'}</ul>
          <a href="/api/phone-home/submissions">List / paginated JSON export</a>
        </section>
        """

    def render_interaction_tab(self, selected_run_id: str = "", preset_task_id: str = "") -> str:
        reg = self.interaction_lab.load_registry()
        runs = self.interaction_lab.list_runs(limit=15)
        active_run = (
            self.interaction_lab.get_run(selected_run_id)
            if selected_run_id
            else (runs[0] if runs else None)
        )

        preset_prompt = ""
        preset_behavior = "mentorship"
        for bt in reg["benchmark_tasks"]:
            if bt["id"] == preset_task_id:
                preset_prompt = bt["prompt"]
                preset_behavior = bt["desired_behavior"]
                break
        if not preset_prompt and reg["benchmark_tasks"]:
            preset_prompt = reg["benchmark_tasks"][0]["prompt"]
            preset_behavior = reg["benchmark_tasks"][0]["desired_behavior"]

        frame_checkboxes = []
        for idx, f in enumerate(reg["frames"]):
            checked = "checked" if idx < 3 else ""
            frame_checkboxes.append(
                f"""
                <label class="card" style="display:block;cursor:pointer;">
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span><input type="checkbox" name="frame_ids" value="{escape(f['id'])}" {checked}> <strong>{escape(f['title'])}</strong></span>
                    <code>{escape(f['digest'][:8])}</code>
                  </div>
                  <div class="muted" style="font-size:0.79rem;margin-top:4px;">{escape(f['description'])}</div>
                  <div style="margin-top:6px;">
                    {_badge('affect: ' + f['presentation'], 'accent')}
                    {_badge('user: ' + f['user_model'], 'neutral')}
                    {_badge('asst: ' + f['assistant_model'], 'neutral')}
                    {_badge('rel: ' + f['relationship'], 'neutral')}
                  </div>
                </label>
                """
            )

        preset_links = "".join(
            f'<a class="btn btn-sm" href="/?tab=interaction&amp;task={escape(bt["id"])}">Load Preset: {escape(bt["title"])}</a> '
            for bt in reg["benchmark_tasks"]
        )

        active_run_html = ""
        if active_run:
            variant_cols = []
            for v in active_run["variants"]:
                r = v.get("ratings") or {}
                is_win = r.get("winner") is True
                win_badge = _badge("★ Winner", "good") if is_win else ""
                score_summary = (
                    f"Usefulness: {r['usefulness']}/5 · Actionability: {r['actionability']}/5 · Initiative: {r['initiative']}/5 · Specificity: {r['specificity']}/5"
                    if r.get("usefulness") is not None
                    else "Not human-graded yet"
                )
                variant_cols.append(
                    f"""
                    <div class="card" style="{'border:2px solid var(--good);' if is_win else ''}">
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <strong>{escape(v['frame_title'])}</strong>
                        <span>{win_badge} <code>{escape(v['manifest_digest'][:10])}</code></span>
                      </div>
                      <div style="margin-bottom:8px;">
                        {_badge('affect: ' + v['components']['presentation'], 'accent')}
                        {_badge('user: ' + v['components']['user_model'], 'neutral')}
                        {_badge('asst: ' + v['components']['assistant_model'], 'neutral')}
                        {_badge('rel: ' + v['components']['relationship'], 'neutral')}
                      </div>
                      <div class="muted" style="font-size:0.78rem;margin-bottom:8px;">
                        Est. Prompt Tokens: <strong>{v['metrics']['prompt_tokens_est']}</strong> ·
                        Est. Output Tokens: <strong>{v['metrics']['output_tokens_est']}</strong> ·
                        Latency: <strong>{v['metrics']['latency_ms']} ms</strong>
                      </div>
                      <details style="margin-bottom:8px;">
                        <summary style="cursor:pointer;font-size:0.82rem;color:var(--accent);">Inspect Compiled InteractionFrame System Envelope</summary>
                        <pre>{escape(v['compiled_prompt'])}</pre>
                      </details>
                      <div style="margin-bottom:10px;">
                        <div class="muted" style="font-size:0.76rem;text-transform:uppercase;margin-bottom:3px;">Framed Output ({escape(active_run['execution_mode'])})</div>
                        <pre>{escape(v['output_text'])}</pre>
                      </div>
                      <form method="post" action="/action/rate-frame" style="border-top:1px solid var(--line);padding-top:8px;">
                        <input type="hidden" name="run_id" value="{escape(active_run['run_id'])}">
                        <input type="hidden" name="frame_id" value="{escape(v['frame_id'])}">
                        <div class="muted" style="font-size:0.78rem;margin-bottom:6px;"><strong>Human Evaluation Rubric:</strong> {escape(score_summary)}</div>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                          <label style="font-size:0.76rem;">Useful <input type="number" name="usefulness" min="1" max="5" value="{r.get('usefulness') or 4}" style="width:48px;padding:3px;"></label>
                          <label style="font-size:0.76rem;">Action <input type="number" name="actionability" min="1" max="5" value="{r.get('actionability') or 4}" style="width:48px;padding:3px;"></label>
                          <label style="font-size:0.76rem;">Init <input type="number" name="initiative" min="1" max="5" value="{r.get('initiative') or 4}" style="width:48px;padding:3px;"></label>
                          <label style="font-size:0.76rem;">Spec <input type="number" name="specificity" min="1" max="5" value="{r.get('specificity') or 4}" style="width:48px;padding:3px;"></label>
                          <label style="font-size:0.76rem;"><input type="checkbox" name="winner" value="1" {"checked" if is_win else ""}> Winner</label>
                          <button type="submit" class="btn btn-sm btn-primary">Save Score</button>
                        </div>
                      </form>
                    </div>
                    """
                )

            active_run_html = f"""
            <section class="panel" style="border-color:var(--accent);">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
                <h2>Side-by-Side Comparison Run: <code>{escape(active_run['run_id'])}</code></h2>
                <div>{_badge(active_run['execution_mode'], 'accent')} · <span class="muted">{escape(active_run['created_at'])}</span></div>
              </div>
              <p><strong>Task Prompt:</strong> {escape(active_run['task_prompt'])}</p>
              <div class="grid-3">{''.join(variant_cols)}</div>
            </section>
            """

        history_rows = []
        for r in runs:
            win_frames = [v["frame_id"] for v in r["variants"] if (v.get("ratings") or {}).get("winner")]
            win_html = _badge("Winner: " + win_frames[0], "good") if win_frames else '<span class="muted">Unscored</span>'
            history_rows.append(
                f"""
                <tr>
                  <td><a href="/?tab=interaction&amp;run_id={escape(r['run_id'])}"><strong><code>{escape(r['run_id'])}</code></strong></a></td>
                  <td>{escape(r['created_at'])}</td>
                  <td>{escape(r['task_prompt'][:110])}…</td>
                  <td>{len(r['variants'])} frames ({', '.join(escape(v['frame_id']) for v in r['variants'])})</td>
                  <td>{win_html}</td>
                </tr>
                """
            )

        return f"""
        <div class="stats-row">
          <div class="stat-card"><div class="stat-label">Registered Frames</div><div class="stat-value">{len(reg['frames'])}</div><div class="stat-sub">Versioned with SHA-256 digests</div></div>
          <div class="stat-card"><div class="stat-label">Affects (Presentation)</div><div class="stat-value">{len(reg['affects'])}</div><div class="stat-sub">{', '.join(reg['affects'].keys())}</div></div>
          <div class="stat-card"><div class="stat-label">User Models</div><div class="stat-value">{len(reg['user_models'])}</div><div class="stat-sub">{', '.join(reg['user_models'].keys())}</div></div>
          <div class="stat-card"><div class="stat-label">Assistant Models</div><div class="stat-value">{len(reg['assistant_models'])}</div><div class="stat-sub">{', '.join(reg['assistant_models'].keys())}</div></div>
          <div class="stat-card"><div class="stat-label">Persisted Eval Runs</div><div class="stat-value">{len(runs)}</div><div class="stat-sub">Stored in SQLite Lab DB</div></div>
        </div>

        <section class="panel">
          <h2>Run Side-by-Side InteractionFrame Evaluation (Observe -&gt; Create Frame -&gt; Benchmark)</h2>
          <p class="muted">Select 2 or more InteractionFrames below and execute them against the same task prompt to compare compiled prompt envelopes, token budgets, and framed outputs side-by-side.</p>
          <div style="margin-bottom:10px;">{preset_links}</div>
          <form method="post" action="/action/run-eval">
            <div style="margin-bottom:12px;">
              <label style="font-weight:600;display:block;margin-bottom:4px;">Task Prompt to Evaluate Across Frames:</label>
              <textarea name="task_prompt" required>{escape(preset_prompt)}</textarea>
            </div>
            <div style="margin-bottom:12px;">
              <label style="font-weight:600;display:block;margin-bottom:6px;">Select InteractionFrames to Compare Side-by-Side:</label>
              <div class="grid-3">{''.join(frame_checkboxes)}</div>
            </div>
            <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
              <label>Desired Behavior Tag: <input type="text" name="desired_behavior" value="{escape(preset_behavior)}"></label>
              <button type="submit" class="btn btn-primary">Execute Side-by-Side Frame Evaluation</button>
            </div>
          </form>
        </section>

        {active_run_html}

        <div class="grid-2">
          <section class="panel">
            <h2>Compose &amp; Version a New InteractionFrame</h2>
            <p class="muted">Combine any Presentation Affect, User Model, Assistant Model, and Relationship into a new content-addressed frame.</p>
            <form method="post" action="/action/create-frame" style="display:grid;gap:10px;">
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <label>Frame ID Slug:<br><input type="text" name="frame_id" placeholder="e.g. cute_critic_peer" required style="width:100%;"></label>
                <label>Display Title:<br><input type="text" name="title" placeholder="e.g. Gentle Adversarial Peer" required style="width:100%;"></label>
              </div>
              <label>Description / Hypothesis:<br><input type="text" name="description" placeholder="Why this combination improves task outcomes…" required style="width:100%;"></label>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <label>1. Presentation (Affect):<br>
                  <select name="presentation" style="width:100%;">
                    {''.join(f'<option value="{escape(k)}">{escape(v["title"])} ({escape(k)})</option>' for k, v in reg['affects'].items())}
                  </select>
                </label>
                <label>2. User Model:<br>
                  <select name="user_model" style="width:100%;">
                    {''.join(f'<option value="{escape(k)}">{escape(v["title"])} ({escape(k)})</option>' for k, v in reg['user_models'].items())}
                  </select>
                </label>
                <label>3. Assistant Model:<br>
                  <select name="assistant_model" style="width:100%;">
                    {''.join(f'<option value="{escape(k)}">{escape(v["title"])} ({escape(k)})</option>' for k, v in reg['assistant_models'].items())}
                  </select>
                </label>
                <label>4. Relationship:<br>
                  <select name="relationship" style="width:100%;">
                    {''.join(f'<option value="{escape(k)}">{escape(v["title"])} ({escape(k)})</option>' for k, v in reg['relationships'].items())}
                  </select>
                </label>
              </div>
              <button type="submit" class="btn btn-primary">Register &amp; Version InteractionFrame</button>
            </form>
          </section>

          <section class="panel">
            <h2>Persisted Evaluation Runs ({len(runs)})</h2>
            <table>
              <thead><tr><th>Run ID</th><th>Timestamp</th><th>Task</th><th>Variants</th><th>Outcome</th></tr></thead>
              <tbody>{''.join(history_rows) or '<tr><td colspan="5" class="muted">No runs recorded yet. Click "Execute Side-by-Side Frame Evaluation" above!</td></tr>'}</tbody>
            </table>
          </section>
        </div>
        """


    def render_conversations_tab(
            self,
            query: str = "",
            platform_filter: str = "",
            model_filter: str = "",
            selected_session_id: str = "",
        ) -> str:
            from .conversations import extract_code_blocks, estimate_tokens
            from .handoff import compile_context_handoff

            data = self.conversations_hub.get_all_conversations(
                query=query,
                platform_filter=platform_filter,
                model_filter=model_filter,
            )
            summary = data["summary"]
            sessions = data["sessions"]

            # If no session selected, select the first one
            selected_session = None
            if selected_session_id:
                for s in sessions:
                    if s["session_id"] == selected_session_id or s.get("full_session_id", "").startswith(selected_session_id):
                        selected_session = s
                        break
            if not selected_session and sessions:
                selected_session = sessions[0]

            # Analytics & Tokenomics Cards
            plat_chips = " · ".join(f"{p}: {c}" for p, c in summary["platforms"].items()) or "None detected"
            model_chips = " · ".join(f"{m}: {c}" for m, c in summary["models"].items()) or "None detected"

            stats_html = f"""
            <div class="stats-row">
              <div class="stat-card">
                <div class="stat-label">Total AI Sessions</div>
                <div class="stat-value">{summary['total_sessions']}</div>
                <div class="stat-sub">{summary['filtered_sessions']} matching active filters</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Dialogue Turns</div>
                <div class="stat-value">{summary['total_turns']}</div>
                <div class="stat-sub">Across all connected harnesses</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Tokenomics (Est. Total)</div>
                <div class="stat-value">~{summary['est_total_tokens']:,}</div>
                <div class="stat-sub">In: ~{summary['est_input_tokens']:,} · Out: ~{summary['est_output_tokens']:,}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Active Platforms</div>
                <div class="stat-value" style="font-size:1.1rem;margin-top:6px;">{len(summary['platforms'])} Connected</div>
                <div class="stat-sub">{escape(plat_chips)}</div>
              </div>
              <div class="stat-card">
                <div class="stat-label">Models Tracked</div>
                <div class="stat-value" style="font-size:1.1rem;margin-top:6px;">{len(summary['models'])} Models</div>
                <div class="stat-sub">{escape(model_chips)}</div>
              </div>
            </div>
            """

            # Onboarding / Ingest Hub Drawer
            onboard_drawer = f"""
            <details class="panel" style="border: 1px dashed var(--accent); margin-bottom: 20px;">
              <summary style="cursor:pointer; font-weight:600; font-size:1.05rem; color:var(--accent);">
                ＋ Onboard / Ingest External Chat (Microsoft Copilot, Cloud Export, ChatGPT, Claude)
              </summary>
              <div style="margin-top:14px;">
                <p class="muted">Paste raw conversational transcripts from Microsoft Copilot (Bing/M365), web GitHub Copilot, ChatGPT, or Claude to make them searchable, tokenized, and copyable alongside local sessions.</p>
                <form method="post" action="/action/import-chat">
                  <div class="grid-3" style="margin-bottom:12px;">
                    <div>
                      <label style="display:block; font-size:0.8rem; margin-bottom:4px; font-weight:600;">Platform / Source</label>
                      <select name="platform" style="width:100%;">
                        <option value="Microsoft Copilot">Microsoft Copilot (Bing / Windows / M365)</option>
                        <option value="GitHub Copilot Web">GitHub Copilot (Remote Web)</option>
                        <option value="Claude Web">Claude (Web / Project)</option>
                        <option value="ChatGPT Web">ChatGPT (OpenAI)</option>
                        <option value="Custom Agent">Custom Agent / Terminal</option>
                      </select>
                    </div>
                    <div>
                      <label style="display:block; font-size:0.8rem; margin-bottom:4px; font-weight:600;">Model Identifier</label>
                      <input type="text" name="model" value="GPT-4o / Copilot" placeholder="e.g. GPT-4o, Claude 3.5 Sonnet, Gemini" style="width:100%;">
                    </div>
                    <div>
                      <label style="display:block; font-size:0.8rem; margin-bottom:4px; font-weight:600;">Conversation Title / Topic</label>
                      <input type="text" name="title" placeholder="e.g. Strategy Brainstorm" style="width:100%;" required>
                    </div>
                  </div>
                  <div style="margin-bottom:12px;">
                    <label style="display:block; font-size:0.8rem; margin-bottom:4px; font-weight:600;">Transcript Text / Export Content</label>
                    <textarea name="raw_text" placeholder="Paste the multi-turn chat text, formatted export, or prompt/answer sequence here…" style="width:100%; height:130px; font-family:monospace; font-size:0.82rem;" required></textarea>
                  </div>
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span class="muted" style="font-size:0.8rem;">Data persists into local SQLite hub (never committed to git).</span>
                    <button type="submit" class="btn btn-primary">Ingest into Hub</button>
                  </div>
                </form>
              </div>
            </details>
            """

            # Filter Bar
            platform_options = "".join(
                f'<option value="{escape(p)}" {"selected" if platform_filter.lower() == p.lower() else ""}>{escape(p)} ({c})</option>'
                for p, c in summary["platforms"].items()
            )
            model_options = "".join(
                f'<option value="{escape(m)}" {"selected" if model_filter.lower() == m.lower() else ""}>{escape(m)} ({c})</option>'
                for m, c in summary["models"].items()
            )

            filter_bar = f"""
            <form method="get" action="/" style="display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; align-items:center;">
              <input type="hidden" name="tab" value="conversations">
              <input type="search" name="q" value="{escape(query)}" placeholder="Search across all chats, code snippets, prompts, and tool calls…" style="flex:1; min-width:280px;">
              <select name="platform">
                <option value="">All Platforms</option>
                {platform_options}
              </select>
              <select name="model">
                <option value="">All Models</option>
                {model_options}
              </select>
              <button type="submit" class="btn btn-primary">Filter</button>
              <a class="btn" href="/?tab=conversations">Reset</a>
            </form>
            """

            # Sessions Sidebar List
            session_items = []
            for s in sessions:
                is_active = (selected_session and s["session_id"] == selected_session["session_id"])
                p_tone = "accent" if "antigravity" in s["platform"].lower() else ("good" if "vscode" in s["platform"].lower() else "warn")
                session_items.append(f"""
                <a href="/?tab=conversations&amp;session={escape(s['session_id'])}&amp;q={escape(query)}&amp;platform={escape(platform_filter)}&amp;model={escape(model_filter)}"
                   style="display:block; padding:10px 12px; margin-bottom:6px; border-radius:6px; text-decoration:none; color:inherit; background:{'var(--surface-2)' if is_active else 'transparent'}; border:1px solid {'var(--accent)' if is_active else 'var(--line)'};">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">
                    <span class="badge badge-{p_tone}">{escape(s['platform'])}</span>
                    <span class="muted" style="font-size:0.75rem;">{escape(s.get('created_date', '')[:10])}</span>
                  </div>
                  <strong style="font-size:0.86rem; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{escape(s['title'])}</strong>
                  <div class="muted" style="font-size:0.76rem; margin-top:2px;">
                    {s['turn_count']} turns · ~{s['est_total_tokens']:,} tok · {escape(s['model'])}
                  </div>
                </a>
                """)

            # Selected Session Turns Viewer with Granular Copy Controls
            dialogue_html = ""
            if selected_session:
                sid = selected_session["session_id"]
                handoff = compile_context_handoff(
                    session_id=selected_session.get("full_session_id", sid),
                    factory_root=self.factory_root,
                    network_root=self.network_root,
                )
                handoff_md = handoff.get("markdown", "")

                turns_rendered = []
                for t in selected_session.get("turns", []):
                    t_idx = t["turn_index"]
                    u_prompt = t["user_prompt"]
                    a_resp = "\n\n".join(t["assistant_responses"])
                    code_blocks = extract_code_blocks(a_resp)
                    code_btn = ""
                    if code_blocks:
                        all_code = "\n\n---\n\n".join(code_blocks)
                        code_btn = f"""
                        <button class="btn btn-sm" type="button" onclick="copySnippet(`{escape(all_code).replace('`', '\\`')}`, this)">
                          Copy Code Only ({len(code_blocks)})
                        </button>"""

                    full_turn_text = f"USER:\n{u_prompt}\n\nASSISTANT:\n{a_resp}"

                    turns_rendered.append(f"""
                    <div class="card" style="margin-bottom:14px; background:var(--surface);">
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid var(--line); padding-bottom:6px;">
                        <div>
                          <strong>Turn #{t_idx}</strong>
                          <span class="muted" style="font-size:0.78rem; margin-left:8px;">{escape(t.get('timestamp', '')[:19])}</span>
                          <span class="badge badge-neutral" style="font-size:0.72rem; margin-left:6px;">~{estimate_tokens(u_prompt) + estimate_tokens(a_resp)} tok</span>
                        </div>
                        <div style="display:flex; gap:6px;">
                          <button class="btn btn-sm" type="button" onclick="copySnippet(`{escape(full_turn_text).replace('`', '\\`')}`, this)">
                            Copy Turn (Prompt + Reply)
                          </button>
                        </div>
                      </div>

                      <div style="margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                          <span class="badge badge-accent">User Prompt</span>
                          <button class="btn btn-sm" type="button" onclick="copySnippet(`{escape(u_prompt).replace('`', '\\`')}`, this)">Copy Prompt</button>
                        </div>
                        <div style="font-size:0.88rem; padding:8px 10px; background:var(--surface-2); border-radius:6px; white-space:pre-wrap;">{escape(u_prompt)}</div>
                      </div>

                      <div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                          <span class="badge badge-good">Assistant Reply ({escape(selected_session['model'])})</span>
                          <div style="display:flex; gap:6px;">
                            {code_btn}
                            <button class="btn btn-sm" type="button" onclick="copySnippet(`{escape(a_resp).replace('`', '\\`')}`, this)">Copy Reply</button>
                          </div>
                        </div>
                        <div style="font-size:0.86rem; padding:8px 10px; background:var(--surface-2); border-radius:6px; white-space:pre-wrap; max-height:450px; overflow-y:auto;">{escape(a_resp)}</div>
                      </div>
                    </div>
                    """)

                dialogue_html = f"""
                <div style="flex:1; min-width:0;">
                  <div class="panel" style="margin-bottom:14px; border:2px solid var(--accent); background:rgba(124, 106, 255, 0.05);">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                      <div>
                        <div style="display:flex; gap:8px; align-items:center; margin-bottom:4px;">
                          <span class="badge badge-accent">{escape(selected_session['platform'])}</span>
                          <span class="badge badge-neutral">{escape(selected_session['model'])}</span>
                          <span class="muted" style="font-size:0.8rem;">{escape(selected_session.get('created_date', ''))}</span>
                        </div>
                        <h2 style="margin:0 0 4px 0;">{escape(selected_session['title'])}</h2>
                        <p class="muted" style="margin:0; font-size:0.82rem;">{selected_session['turn_count']} dialogue turns · ~{selected_session['est_total_tokens']:,} total tokens ({selected_session['est_input_tokens']:,} in / {selected_session['est_output_tokens']:,} out)</p>
                      </div>
                      <div>
                        <button class="btn btn-primary" type="button" onclick="copySnippet(`{escape(handoff_md).replace('`', '\\`')}`, this)">
                          1-Click Copy Full Handoff Packet
                        </button>
                      </div>
                    </div>
                  </div>
                  {''.join(turns_rendered)}
                </div>
                """
            else:
                dialogue_html = '<div style="flex:1;" class="panel"><p class="muted">No conversations match the current filters.</p></div>'

            # Global copy helper script
            copy_script = """
            <script>
            function copySnippet(text, btn) {
              navigator.clipboard.writeText(text).then(() => {
                const orig = btn.innerText;
                btn.innerText = '✓ Copied!';
                btn.style.borderColor = 'var(--good)';
                btn.style.color = 'var(--good)';
                setTimeout(() => {
                  btn.innerText = orig;
                  btn.style.borderColor = '';
                  btn.style.color = '';
                }, 2000);
              }).catch(err => {
                alert('Clipboard copy error: ' + err);
              });
            }
            </script>
            """

            return f"""
            {stats_html}
            {onboard_drawer}
            {filter_bar}
            <div style="display:flex; gap:16px; align-items:flex-start;">
              <div style="width:340px; flex-shrink:0;">
                <div class="panel" style="padding:12px;">
                  <h3 style="margin:0 0 10px 0; font-size:0.92rem;">Sessions ({len(sessions)})</h3>
                  <div style="max-height:750px; overflow-y:auto;">
                    {''.join(session_items)}
                  </div>
                </div>
              </div>
              {dialogue_html}
            </div>
            {copy_script}
            """




def re_strip_marks(text: str) -> str:
    return text.replace("<mark>", "").replace("</mark>", "")


def _render_file_inspector(inspect_path: str) -> str:
    if not inspect_path:
        return ""
    p = Path(inspect_path)
    if not p.is_file():
        return ""
    try:
        content = p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as exc:
        content = f"Could not read file: {exc}"
    return f"""
    <section id="inspector" class="panel" style="border-color:var(--accent);">
      <h2>Artifact Inspector: <code>{escape(str(p))}</code></h2>
      <pre>{escape(content)}</pre>
    </section>
    """



def make_handler(workbench: ControlPlaneWorkbench) -> type[BaseHTTPRequestHandler]:
    class ControlPlaneHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, html: str, status: int = 200) -> None:
            raw = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_json(self, payload: Any, status: int = 200) -> None:
            raw = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _local_request(self, writing: bool = False) -> bool:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.server.server_port == 80:
                allowed.update(("127.0.0.1", "localhost"))
            if host not in allowed:
                self._send_json({"error": "loopback Host required"}, 403)
                return False
            if writing:
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{host}":
                    self._send_json({"error": "cross-origin writes are not allowed"}, 403)
                    return False
            return True

        def _phone_home_get(self, path: str, qs: dict[str, list[str]]) -> None:
            try:
                limit = int(qs.get("limit", ["20"])[0])
                if path == "/api/phone-home/check":
                    data = workbench.phone_home.check(qs.get("q", [""])[0], limit)
                elif path == "/api/phone-home/submissions":
                    sid = qs.get("id", [""])[0]
                    data = workbench.phone_home.get(sid) if sid else workbench.phone_home.list(
                        qs.get("q", [""])[0], limit, int(qs.get("offset", ["0"])[0]),
                    )
                else:
                    raise PhoneHomeError("endpoint not found", 404)
                self._send_json(data)
            except (ValueError, OSError, sqlite3.Error) as exc:
                status = getattr(exc, "status", 400 if isinstance(exc, ValueError) else 503)
                self._send_json({"error": str(exc), "status": status}, status)

        def _phone_home_submit(self, is_form: bool) -> None:
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise PhoneHomeError("Transfer-Encoding is not supported")
                length_text = self.headers.get("Content-Length", "")
                if not length_text.isdecimal():
                    raise PhoneHomeError("valid Content-Length required")
                length = int(length_text)
                if length > MAX_REQUEST_BYTES:
                    raise PhoneHomeError("submission exceeds 64 KiB", 413)
                media = self.headers.get("Content-Type", "").split(";")[0].strip()
                expected = "application/x-www-form-urlencoded" if is_form else "application/json"
                if media != expected:
                    raise PhoneHomeError(f"Content-Type must be {expected}", 415)
                self.connection.settimeout(10)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise PhoneHomeError("incomplete request body")
                if is_form:
                    form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                    if not secrets.compare_digest(form.get("csrf", [""])[0], workbench.phone_home_csrf):
                        raise PhoneHomeError("invalid form CSRF token", 403)
                    payload = {k: v[0] for k, v in form.items() if k != "csrf"}
                    for field in ("related_refs", "tags"):
                        payload[field] = [s.strip() for s in payload.get(field, "").split(",") if s.strip()]
                else:
                    payload = json.loads(raw.decode("utf-8"))
                receipt = workbench.phone_home.submit(payload)
                if is_form:
                    self._redirect("/?" + urlencode({
                        "tab": "capabilities", "flash": f"Saved {receipt['id']} as provisional intake, not approval.",
                    }))
                else:
                    self._send_json(receipt, 201)
            except (ValueError, OSError, sqlite3.Error) as exc:
                status = getattr(exc, "status", 400 if isinstance(exc, ValueError) else 503)
                self.close_connection = True
                self._send_json({"error": str(exc), "status": status}, status)

        def do_GET(self) -> None:
            if not self._local_request():
                return
            parsed = urlsplit(self.path)
            qs = parse_qs(parsed.query)

            if parsed.path.startswith("/api/phone-home/"):
                self._phone_home_get(parsed.path, qs)
                return

            if parsed.path == "/api/health":
                self._send_json({"ok": True, "version": PACKAGE_VERSION})
                return
            if parsed.path == "/api/portfolio":
                self._send_json(scan_portfolio(workbench.network_root, workbench.factory_root))
                return
            if parsed.path == "/api/queues":
                self._send_json(aggregate_queues(workbench.factory_root, workbench.network_root))
                return
            if parsed.path == "/api/fabric":
                q = qs.get("q", [""])[0]
                kind = qs.get("kind", [""])[0]
                self._send_json(workbench.fabric.search(query=q, kind_filter=kind))
                return
            if parsed.path == "/api/capabilities":
                prob = qs.get("prob", [""])[0]
                self._send_json(discover_capabilities(prob, workbench.factory_root, workbench.fabric))
                return
            if parsed.path == "/api/decision-aid":
                try:
                    aid = build_decision_aid(
                        workbench.factory_root,
                        topic=qs.get("topic", ["infrastructure-decision"])[0],
                        operator_context=qs.get("context", [""])[0],
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                except OSError as exc:
                    self._send_json({"error": f"Decision aid unavailable: {exc}"}, status=500)
                else:
                    self._send_json(aid)
                return
            if parsed.path == "/api/handoff":
                from control_plane.handoff import compile_context_handoff
                sess = qs.get("session", [None])[0]
                turns_s = qs.get("turns", [None])[0]
                turns_limit = int(turns_s) if turns_s and turns_s.isdigit() else 5
                h = compile_context_handoff(
                    session_id=sess,
                    turns_limit=turns_limit,
                    factory_root=workbench.factory_root,
                    network_root=workbench.network_root,
                )
                self._send_json(h)
                return
            if parsed.path == "/api/interaction":
                self._send_json(
                    {
                        "registry": workbench.interaction_lab.load_registry(),
                        "runs": workbench.interaction_lab.list_runs(),
                    }
                )
                return

            tab = qs.get("tab", ["portfolio"])[0]
            flash = qs.get("flash", [""])[0]
            inspect_path = qs.get("inspect", [""])[0]
            inspector_html = _render_file_inspector(inspect_path)

            if tab == "queues":
                body = workbench.render_queues_tab(
                    owner_filter=qs.get("owner", [""])[0],
                    bucket_filter=qs.get("bucket", [""])[0],
                    route_query=qs.get("route_q", [""])[0],
                ) + inspector_html
                self._send_html(_layout("queues", "Queues & Next Actions", body, flash=flash))
            elif tab == "fabric":
                body = workbench.render_fabric_tab(
                    query=qs.get("q", [""])[0],
                    kind_filter=qs.get("kind", [""])[0],
                    entity_id=qs.get("entity", [""])[0],
                )
                self._send_html(_layout("fabric", "Knowledge & Conversation Fabric", body, flash=flash))
            elif tab == "conversations":
                body = workbench.render_conversations_tab(
                    query=qs.get("q", [""])[0],
                    platform_filter=qs.get("platform", [""])[0],
                    model_filter=qs.get("model", [""])[0],
                    selected_session_id=qs.get("session", [""])[0],
                )
                self._send_html(_layout("conversations", "Conversations & Tokenomics", body, flash=flash))
            elif tab == "capabilities":
                body = workbench.render_capabilities_tab(
                    problem_query=qs.get("prob", [""])[0],
                    aid_topic=qs.get("aid_topic", ["infrastructure-decision"])[0],
                    aid_context=qs.get("aid_context", [""])[0],
                )
                self._send_html(_layout("capabilities", "Capability Discovery", body, flash=flash))
            elif tab == "interaction":
                body = workbench.render_interaction_tab(
                    selected_run_id=qs.get("run_id", [""])[0],
                    preset_task_id=qs.get("task", [""])[0],
                )
                self._send_html(_layout("interaction", "Interaction Frame Lab", body, flash=flash))
            else:
                inc_wt = qs.get("worktrees", ["0"])[0] == "1"
                body = workbench.render_portfolio_tab(include_worktrees=inc_wt) + inspector_html
                self._send_html(_layout("portfolio", "Portfolio & Network", body, flash=flash))

        def do_POST(self) -> None:
            if not self._local_request(writing=True):
                return
            parsed = urlsplit(self.path)
            if parsed.path in ("/api/phone-home/submissions", "/action/phone-home-submit"):
                self._phone_home_submit(parsed.path.startswith("/action/"))
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw_body)

            if parsed.path == "/action/open-repo":
                target = form.get("path", [""])[0]
                mode = form.get("mode", ["explorer"])[0]
                res = open_repo_location(target, mode=mode)
                msg = f"Opened {res.get('path')} in {mode}" if res.get("ok") else f"Error: {res.get('error')}"
                self._redirect("/?" + urlencode({"tab": "portfolio", "flash": msg}))
                return

            if parsed.path == "/action/rebuild-fabric":
                counts = workbench.fabric.rebuild(include_conversations=True)
                msg = f"Rebuilt Fabric FTS5 index: {counts['knowledge_entities']} Factory entities + {counts['conversations_indexed']} AI conversations indexed."
                self._redirect("/?" + urlencode({"tab": "fabric", "flash": msg}))
                return

            if parsed.path == "/action/import-chat":
                title = form.get("title", [""])[0]
                platform = form.get("platform", ["Microsoft Copilot (Imported)"])[0]
                model = form.get("model", ["Copilot / GPT-4"])[0]
                raw_text = form.get("raw_text", [""])[0]
                workspace = form.get("workspace", ["General"])[0]
                if raw_text.strip():
                    imp = workbench.conversations_hub.import_external_chat(
                        title=title,
                        platform=platform,
                        model=model,
                        raw_text=raw_text,
                        workspace=workspace,
                    )
                    msg = f"Successfully imported '{imp['title']}' ({imp['est_tokens']} est. tokens) into Conversation Hub!"
                    self._redirect("/?" + urlencode({"tab": "conversations", "session": imp["session_id"], "flash": msg}))
                else:
                    self._redirect("/?" + urlencode({"tab": "conversations", "flash": "Error: Transcript cannot be empty."}))
                return

            if parsed.path == "/action/run-eval":
                task_prompt = form.get("task_prompt", [""])[0]
                frame_ids = form.get("frame_ids", [])
                desired = form.get("desired_behavior", ["general"])[0]
                if not frame_ids:
                    frame_ids = ["baseline_direct", "cute_mentor_builder"]
                run = workbench.interaction_lab.run_side_by_side_evaluation(
                    task_prompt=task_prompt,
                    frame_ids=frame_ids,
                    desired_behavior=desired,
                )
                self._redirect(
                    "/?"
                    + urlencode(
                        {
                            "tab": "interaction",
                            "run_id": run["run_id"],
                            "flash": f"Completed side-by-side evaluation {run['run_id']} across {len(frame_ids)} InteractionFrames.",
                        }
                    )
                )
                return

            if parsed.path == "/action/create-frame":
                created = workbench.interaction_lab.save_custom_frame(
                    frame_id=form.get("frame_id", ["custom_frame"])[0],
                    title=form.get("title", ["Custom Frame"])[0],
                    description=form.get("description", [""])[0],
                    presentation=form.get("presentation", ["neutral"])[0],
                    user_model=form.get("user_model", ["standard_developer"])[0],
                    assistant_model=form.get("assistant_model", ["default_assistant"])[0],
                    relationship=form.get("relationship", ["transactional"])[0],
                )
                self._redirect(
                    "/?"
                    + urlencode(
                        {
                            "tab": "interaction",
                            "flash": f"Registered InteractionFrame '{created['id']}' (SHA-256 digest: {created['digest']}).",
                        }
                    )
                )
                return

            if parsed.path == "/action/rate-frame":
                run_id = form.get("run_id", [""])[0]
                frame_id = form.get("frame_id", [""])[0]
                workbench.interaction_lab.record_human_rating(
                    run_id=run_id,
                    frame_id=frame_id,
                    usefulness=int(form.get("usefulness", ["4"])[0]),
                    actionability=int(form.get("actionability", ["4"])[0]),
                    initiative=int(form.get("initiative", ["4"])[0]),
                    specificity=int(form.get("specificity", ["4"])[0]),
                    winner=form.get("winner", ["0"])[0] == "1",
                )
                self._redirect(
                    "/?"
                    + urlencode(
                        {
                            "tab": "interaction",
                            "run_id": run_id,
                            "flash": f"Saved human evaluation scores for frame '{frame_id}' in {run_id}.",
                        }
                    )
                )
                return

            self._redirect("/")

    return ControlPlaneHandler


def serve_control_plane(
    host: str = "127.0.0.1",
    port: int = 8780,
    open_browser: bool = False,
    workbench: ControlPlaneWorkbench | None = None,
    seed_evaluation: bool = False,
) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("workbench must bind to loopback (127.0.0.1 or localhost)")
    wb = workbench or ControlPlaneWorkbench()
    if not wb.fabric.freshness()["built"]:
        wb.fabric.rebuild(include_conversations=False)
    # Seed an initial side-by-side benchmark run if the database has zero runs so the operator immediately sees a comparison
    if seed_evaluation and not wb.interaction_lab.list_runs(limit=1):
        reg = wb.interaction_lab.load_registry()
        default_task = reg["benchmark_tasks"][0]
        wb.interaction_lab.run_side_by_side_evaluation(
            task_prompt=default_task["prompt"],
            frame_ids=["baseline_direct", "cute_mentor_builder", "caveman_principal_peer"],
            desired_behavior=default_task["desired_behavior"],
            notes="Initial seed comparison generated on first launch",
        )
    server = ThreadingHTTPServer((host, port), make_handler(wb))
    if open_browser:
        url = f"http://{host}:{server.server_port}/"
        webbrowser.open(url)
    return server
