"""Optional official-SDK MCP adapter. Transport is local stdio only."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .phone_home import KINDS, PhoneHome, PhoneHomeError
from .material_capability import FORMATS
from .operational_handoffs import contracts as handoff_contracts
from .precedents import find_precedents, inspect_precedent


def tool_contracts() -> list[dict[str, Any]]:
    def string(maximum: int, required: bool = False) -> dict[str, Any]:
        return {"type": "string", "maxLength": maximum, **({"minLength": 1} if required else {})}

    def tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"name": name, "description": description,
                "inputSchema": {"type": "object", "properties": properties,
                                "required": required, "additionalProperties": False},
                "outputSchema": {"type": "object"}}

    limit = {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}
    query = string(2000)
    fields = {"kind": {"type": "string", "enum": [*KINDS, "material"]},
              "title": string(200, True), "summary": string(20000, True),
              "source_repo": string(1000, True), "reuse_query": string(2000, True),
              "schema_version": {"type": "integer", "const": 1, "default": 1},
              "external_evidence": string(20000)}
    fields["target"] = string(2000)
    fields["material"] = {
        "type": "object", "additionalProperties": False,
        "properties": {"name": string(200, True), "format": {"type": "string", "enum": list(FORMATS)},
                       "identity": string(1000, True), "text": string(32768), "base64": string(43692)},
        "required": ["name", "format"],
        "oneOf": [{"required": ["text"]}, {"required": ["base64"]}],
    }
    scope = {
        "type": "object", "additionalProperties": False,
        "properties": {name: string(500) for name in ("runtime", "input", "constraints")},
        "required": ["runtime", "input", "constraints"],
    }
    observation = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "event_id": string(200, True),
            "event_type": {"type": "string", "enum": ["observation", "correction", "dispute"]},
            "target_id": string(200),
            "need": string(2000),
            "outcome": {"type": "string", "enum": ["success", "failure", "mixed", "inconclusive", "unknown"]},
            "scope": scope,
            "summary": string(4000, True),
            "source_ref": string(2000, True),
            "revision": {"type": ["string", "null"], "maxLength": 200},
        },
        "required": ["event_id", "event_type", "target_id", "need", "outcome", "scope",
                     "summary", "source_ref", "revision"],
    }
    precedent_records = {
        "type": "array", "maxItems": 50,
        "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "record_id": string(200, True),
                "record_revision": {"type": ["string", "null"], "maxLength": 200},
                "record_ref": string(2000, True),
                "technique": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"id": string(200, True), "title": string(200, True), "summary": string(4000)},
                    "required": ["id", "title", "summary"],
                },
                "implementation": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "id": string(200, True), "source_ref": string(2000, True),
                        "revision": {"type": ["string", "null"], "maxLength": 200},
                    },
                    "required": ["id", "source_ref", "revision"],
                },
                "observations": {"type": "array", "maxItems": 200, "items": observation},
            },
            "required": ["record_id", "record_revision", "record_ref", "technique", "implementation", "observations"],
        },
    }
    context = {
        "type": "object", "additionalProperties": False,
        "properties": {name: string(500) for name in ("runtime", "input", "constraints")},
    }
    for name in ("source_session", "source_ref", "idempotency_key"):
        fields[name] = string(1000)
    for name in ("tags", "related_refs"):
        fields[name] = {"type": "array", "items": string(200, True), "maxItems": 20}
    contracts = [
        tool("phone_home_check", "Ordered local reuse check before building; human choice, no external research.",
             {"query": string(2000, True), "limit": limit}, ["query"]),
        tool("phone_home_submit", "Ingest supplied material or a report locally in one submission; no acceptance gate or canonical promotion.",
             fields, ["kind"]),
        tool("phone_home_list", "List/export provisional intake with pagination, not canonical knowledge.",
             {"query": query, "limit": limit, "offset": {"type": "integer", "minimum": 0, "default": 0}}, []),
        tool("phone_home_get", "Export a submission for human review/manual promotion outside DNCP.",
             {"submission_id": string(108, True)}, ["submission_id"]),
        tool("devnet_get_portfolio_status", "Query Git states, branches, and modified files across the local development network repositories.",
             {"include_worktrees": {"type": "boolean"}}, []),
        tool("devnet_get_next_actions", "Query aggregated work queues across products, high-leverage next actions, and items awaiting human acceptance.",
             {"owner": string(50), "bucket": string(50), "route_query": string(500)}, []),
        tool("devnet_search_fabric", "Full-text FTS5 search across architectural records (ADRs, DEC, FND, PAT, SRC, ART), runbooks, and indexed AI conversation logs. "
             "Set include_conversation_hub to also search the user's indexed Conversation Hub library of past AI chats (personal, untrusted reference text; "
             "hits carry conversation_id, revision and message_offset for reading the conversation through Conversation Hub).",
             {"query": string(2000, True), "kind": string(50), "limit": limit,
              "include_conversation_hub": {"type": "boolean", "default": False}}, ["query"]),
        tool("devnet_find_precedents",
             "Lexically retrieve caller-supplied precedent records by need; no fetching, indexing, endorsement, or feedback writes.",
             {"query": string(2000, True), "records": precedent_records, "context": context,
              "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}},
             ["query", "records"]),
        tool("devnet_inspect_precedent",
             "Inspect caller-supplied revision-scoped precedent evidence and corrections; no fetching or endorsement.",
             {"implementation_id": string(200, True), "records": precedent_records},
             ["implementation_id", "records"]),
        tool("devnet_get_context_handoff", "Compile a structured, self-contained Context Handoff Packet (active conversation turns, current git branch/diff, and open gates) for cross-session/cross-harness AI context transfer.",
             {"session_id": string(100), "turns_limit": {"type": "integer", "minimum": 1, "maximum": 50}}, []),
    ]
    contracts[1]["inputSchema"]["oneOf"] = [
        {"properties": {"kind": {"const": "material"}}, "required": ["material"]},
        {"properties": {"kind": {"enum": list(KINDS)}},
         "required": ["title", "summary", "source_repo", "reuse_query"]},
    ]
    for name, fields in handoff_contracts().items():
        contracts.append(tool(
            name, "Store untrusted operational data locally; no dispatch, acceptance or authority.",
            fields, [field for field in fields if field != "requested_action"],
        ))
    from .handoff_prepare import contract as handoff_prepare_contract
    contracts.extend([
        tool("handoff_prepare",
             "Read-only: draft a handoff packet whose source_refs cite related past handoffs, Fabric records, "
             "components of registered ALM ledgers and indexed Conversation Hub conversations. References only, no conversation text; nothing is stored "
             "or submitted. Review the draft, then call handoff_submit.",
             handoff_prepare_contract(), []),
        tool("handoff_search",
             "Read-only: find past handoffs in any state, including completed ones, ranked by relevance to "
             "query across requested action, context, blockers and reported results; newest first without a "
             "query. Caller-reported, untrusted history, not verified completion. Exact scope/recipient filters.",
             {"query": string(2000), "scope": string(200), "recipient": string(200),
              "state": {"type": "string", "enum": ["received", "blocked", "preview", "completed"]},
              "limit": limit}, []),
        tool("handoff_get", "Read a packet and latest caller-reported result, not verified completion.",
             {"handoff_id": string(100, True)}, ["handoff_id"]),
        tool("handoff_list", "List pending requests only; information needs no acceptance. Exact filters.",
             {"recipient": string(200), "scope": string(200), "limit": limit,
              "offset": {"type": "integer", "minimum": 0, "maximum": 2147483647, "default": 0}}, []),
    ])
    stage = {"type": "string", "enum": ["", "before-building", "before-claiming-done"]}
    contracts.extend([
        tool("network_bootstrap",
             "Start here from any repository: the network's principles, how to ask for lessons, request new work and "
             "find procedures, plus the playbook names and what is open. Small on purpose.", {}, []),
        tool("playbook_list", "Procedures (SKILL.md) owned by the registry, the incubator and the harvest playbooks.", {}, []),
        tool("playbook_get", "One playbook in full. Read it before following it.", {"name": string(80, True)}, ["name"]),
        tool("lessons_ask",
             "Lessons from past work that apply to a task, from the Epistemic Service: concise claims with what to check, "
             "limits, evidence refs and how well supported each is. Call before building and before saying work is done.",
             {"task": string(2000, True), "repo": string(200), "stage": stage}, ["task"]),
        tool("registry_list", "Network registry entries, optionally by kind, status or initializing node. Read-only.",
             {"kind": string(40), "status": string(40), "initialized_by": string(80)}, []),
        tool("registry_show", "One registry entry. Read-only.", {"id": string(120, True)}, ["id"]),
        tool("commission_check",
             "Read-only first step for a request for new work: registry candidates, existing capabilities, applicable "
             "lessons and the playbook to follow. Read the candidates before opening anything.",
             {"title": string(200, True), "need": string(4000, True), "source_repo": string(300)}, ["title", "need"]),
        tool("commission_open",
             "Record a request. Attaches to existing_entry when the check found it is already in the registry; otherwise "
             "writes a new 'caught' registry entry. Returns the next step. Does not decide anything.",
             {"title": string(200, True), "need": string(4000, True), "requested_by": string(200, True),
              "source_repo": string(300), "kind": {"type": "string", "enum": ["product", "tool", "library", "skill", "research", "issue", "capability"]},
              "existing_entry": string(120)}, ["title", "need", "requested_by"]),
        tool("commission_decide",
             "Record the owner's triage decision as their words (quote); never decide for them. The decision is stored as your record, marked unverified. outcome: idea, seed, routed, adopted, parked or "
             "set-aside. routed/adopted need home. seed needs prior_art, name and category, and runs the incubator's "
             "init-seed to create the repository and set the entry's home.",
             {"id": string(80, True), "outcome": {"type": "string", "enum": ["idea", "seed", "routed", "adopted", "parked", "set-aside"]},
              "reason": string(2000, True), "decided_by": string(200, True), "quote": string(1000, True), "home": string(500),
              "prior_art": string(4000), "name": string(64), "category": {"type": "string", "enum": ["", "products", "shared", "devnet", "research"]},
              "core": string(600)}, ["id", "outcome", "reason", "decided_by", "quote"]),
        tool("commission_progress",
             "Report a decided commission as in-progress, blocked or done, with a note and optional evidence ref. "
             "'done' is the worker's report, not the owner's acceptance.",
             {"id": string(80, True), "state": {"type": "string", "enum": ["in-progress", "blocked", "done"]},
              "note": string(2000, True), "by": string(200, True), "ref": string(500)}, ["id", "state", "note", "by"]),
        tool("registry_note",
             "Record something the owner said in passing against an existing registry entry. Creates no commission and "
             "puts nothing in the owner's queue. Use this, not commission_open, unless the owner asked for work.",
             {"id": string(120, True), "text": string(2000, True), "by": string(200, True), "source": string(500)},
             ["id", "text", "by"]),
        tool("commission_recommend",
             "Triage's product: the outcome you advise, your reasoning, sources (ref plus what each says) and the single "
             "question for the owner. Moves a commission from triage to awaiting-decision, the owner's queue.",
             {"id": string(80, True), "outcome": {"type": "string", "enum": ["idea", "seed", "routed", "adopted", "parked", "set-aside"]},
              "reasoning": string(4000, True), "question": string(600, True), "by": string(200, True),
              "sources": {"type": "array", "maxItems": 20, "items": {"type": "object", "additionalProperties": False,
                          "properties": {"ref": string(500, True), "says": string(600, True), "checked": string(20)},
                          "required": ["ref", "says"]}},
              "alternatives": string(2000), "brief": string(80)}, ["id", "outcome", "reasoning", "question", "by"]),
        tool("commission_withdraw", "Take back an undecided commission opened by mistake; the entry stays.",
             {"id": string(80, True), "reason": string(1000, True), "by": string(200, True)}, ["id", "reason", "by"]),
        tool("commission_get", "One commission with its history and registry entry.", {"id": string(80, True)}, ["id"]),
        tool("commission_list", "Commissions, optionally by state.",
             {"state": {"type": "string", "enum": ["", "triage", "awaiting-decision", "decided", "in-progress", "blocked", "done", "withdrawn"]}}, []),
    ])
    return contracts


def front_door_call(service: PhoneHome, name: str, arguments: dict[str, Any]) -> Any:
    from . import front_door, network_registry
    from .cli import build_commissioning
    root = network_registry.find_registry_root(service.network_root)
    get = arguments.get
    if name == "network_bootstrap":
        return front_door.bootstrap(root, service.factory_root, service.network_root, service.data_dir)
    if name == "playbook_list":
        return front_door.list_playbooks(root, service.factory_root, service.network_root)
    if name == "playbook_get":
        return front_door.get_playbook(get("name"), root, service.factory_root, service.network_root)
    if name == "lessons_ask":
        return front_door.ask_lessons(service.network_root, get("task"), get("repo", ""), get("stage", ""))
    if name == "registry_list":
        return network_registry.list_entries(root, get("kind", ""), get("status", ""), get("initialized_by", ""))
    if name == "registry_show":
        return network_registry.get_entry(root, get("id"))
    desk = build_commissioning(service.factory_root, service.network_root, service.data_dir)
    if name == "registry_note":
        return desk.note(get("id"), get("text"), get("by"), get("source", ""))
    if name == "commission_check":
        return desk.check(get("title"), get("need"), get("source_repo", ""))
    if name == "commission_open":
        return desk.open(get("title"), get("need"), get("requested_by"), get("source_repo", ""),
                         get("kind", "capability"), get("existing_entry", ""))
    if name == "commission_decide":
        return desk.decide(get("id"), get("outcome"), get("reason"), get("decided_by"), get("home", ""),
                           get("prior_art", ""), get("name", ""), get("category", ""), get("core", ""), get("quote", ""))
    if name == "commission_progress":
        return desk.progress(get("id"), get("state"), get("note"), get("by"), get("ref", ""))
    if name == "commission_recommend":
        return desk.recommend(get("id"), get("outcome"), get("reasoning"), get("question"), get("by"),
                              get("sources"), get("alternatives", ""), get("brief", ""))
    if name == "commission_withdraw":
        return desk.withdraw(get("id"), get("reason"), get("by"))
    if name == "commission_get":
        return desk.get(get("id"))
    return desk.list(get("state", ""))


FRONT_DOOR_TOOLS = frozenset({
    "network_bootstrap", "playbook_list", "playbook_get", "lessons_ask", "registry_list", "registry_show", "registry_note",
    "commission_recommend", "commission_withdraw",
    "commission_check", "commission_open", "commission_decide", "commission_progress", "commission_get", "commission_list",
})


def search_fabric(service: PhoneHome, arguments: dict[str, Any]) -> dict[str, Any]:
    """Fabric search for the MCP tool; Conversation Hub text is included only on request."""
    include_hub = arguments.get("include_conversation_hub", False)
    if type(include_hub) is not bool:
        raise PhoneHomeError("include_conversation_hub must be a boolean")
    limit = arguments.get("limit", 20)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise PhoneHomeError("limit must be an integer from 1 to 50")
    kind = arguments.get("kind", "")
    query = arguments.get("query")
    if not isinstance(query, str) or not isinstance(kind, str):
        raise PhoneHomeError("query and kind must be strings")
    result = service.fabric.search(query=query, kind_filter=kind, limit=limit, include_hub=include_hub)
    if include_hub:
        from . import hub_index
        result["conversation_hub"] = service.fabric.freshness()["conversation_hub"]
        result["notice"] = hub_index.NOTICE
    return result


def create_mcp_server(service: PhoneHome) -> Any:
    try:
        from mcp.server import Server
        from mcp.types import CallToolResult, TextContent, Tool
    except ImportError as exc:
        raise RuntimeError('MCP extra missing. Install locally with: pip install "devnet-control-plane[mcp]"') from exc
    server = Server("devnet-phone-home")
    contracts = {item["name"]: item for item in tool_contracts()}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**contract) for contract in contracts.values()]

    # Shared validation avoids SDK coercion/ignored extra fields and prevents
    # schema-error messages from echoing sensitive input values.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        try:
            if name not in contracts:
                raise PhoneHomeError("unknown phone-home tool", 404)
            allowed = contracts[name]["inputSchema"]["properties"]
            if set(arguments) - set(allowed):
                raise PhoneHomeError("unknown tool argument fields")
            if name in FRONT_DOOR_TOOLS:
                return front_door_call(service, name, arguments)
            if name == "phone_home_check":
                return service.check(arguments.get("query"), arguments.get("limit", 20))
            if name == "phone_home_submit":
                return service.submit(arguments)
            if name == "phone_home_list":
                return service.list(arguments.get("query", ""), arguments.get("limit", 20), arguments.get("offset", 0))
            if name == "handoff_submit":
                return service.handoff_submit(arguments)
            if name == "handoff_result":
                return service.handoff_result(arguments)
            if name == "handoff_prepare":
                return service.handoff_prepare(arguments)
            if name == "handoff_search":
                return service.handoff_search(
                    arguments.get("query", ""), arguments.get("scope", ""), arguments.get("recipient", ""),
                    arguments.get("state", ""), arguments.get("limit", 10))
            if name == "handoff_get":
                return service.handoff_get(arguments.get("handoff_id"))
            if name == "handoff_list":
                return service.handoff_list(arguments.get("recipient", ""), arguments.get("scope", ""),
                                            arguments.get("limit", 20), arguments.get("offset", 0))
            if name == "phone_home_get":
                return service.get(arguments.get("submission_id"))
            if name == "devnet_get_portfolio_status":
                from .portfolio import scan_portfolio
                return scan_portfolio(service.network_root, service.factory_root, include_worktrees=arguments.get("include_worktrees", False))
            if name == "devnet_get_next_actions":
                from .queues import aggregate_queues, match_router_route
                qdata = aggregate_queues(service.factory_root, service.network_root)
                owner = arguments.get("owner")
                bucket = arguments.get("bucket")
                route_q = arguments.get("route_query")
                res = {
                    "summary": qdata["summary"],
                    "next_actions": qdata["next_actions"],
                    "awaiting_acceptance": qdata["awaiting_acceptance"],
                }
                if route_q:
                    res["route_match"] = match_router_route(route_q)
                items = [i for i in qdata["all_items"] if not i.get("is_pointer")]
                if owner:
                    items = [i for i in items if i.get("owner_id") == owner]
                if bucket:
                    items = [i for i in items if i.get("bucket") == bucket]
                res["items"] = items[:30]
                return res
            if name == "devnet_search_fabric":
                return search_fabric(service, arguments)
            if name == "devnet_find_precedents":
                return find_precedents(
                    arguments.get("query"), arguments.get("records"), arguments.get("context"),
                    arguments.get("limit", 10),
                )
            if name == "devnet_inspect_precedent":
                return inspect_precedent(arguments.get("implementation_id"), arguments.get("records"))
            if name == "devnet_get_context_handoff":
                from .handoff import compile_context_handoff
                return compile_context_handoff(
                    session_id=arguments.get("session_id"),
                    turns_limit=arguments.get("turns_limit", 5),
                    factory_root=service.factory_root,
                    network_root=service.network_root,
                )
            raise PhoneHomeError(f"unhandled tool: {name}", 400)
        except (ValueError, OSError, sqlite3.Error) as exc:
            error = {"error": str(exc), "status": getattr(exc, "status", 400 if isinstance(exc, ValueError) else 503)}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(error))], isError=True)

    server.execute_tool = call_tool
    return server


def run_mcp(service: PhoneHome) -> None:
    server = create_mcp_server(service)
    import anyio
    from mcp.server.stdio import stdio_server

    async def run() -> None:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    anyio.run(run)
