"""Optional official-SDK MCP adapter. Transport is local stdio only."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .phone_home import KINDS, PhoneHome, PhoneHomeError


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
    fields = {"kind": {"type": "string", "enum": list(KINDS)},
              "title": string(200, True), "summary": string(20000, True),
              "source_repo": string(1000, True), "reuse_query": string(2000, True),
              "schema_version": {"type": "integer", "const": 1, "default": 1},
              "external_evidence": string(20000)}
    for name in ("source_session", "source_ref", "idempotency_key"):
        fields[name] = string(1000)
    for name in ("tags", "related_refs"):
        fields[name] = {"type": "array", "items": string(200, True), "maxItems": 20}
    return [
        tool("phone_home_check", "Ordered local reuse check before building; human choice, no external research.",
             {"query": string(2000, True), "limit": limit}, ["query"]),
        tool("phone_home_submit", "Append unverified provisional intake; never approves or writes incubator records.",
             fields, ["kind", "title", "summary", "source_repo", "reuse_query"]),
        tool("phone_home_list", "List/export provisional intake with pagination, not canonical knowledge.",
             {"query": query, "limit": limit, "offset": {"type": "integer", "minimum": 0, "default": 0}}, []),
        tool("phone_home_get", "Export a submission for human review/manual promotion outside DNCP.",
             {"submission_id": string(100, True)}, ["submission_id"]),
    ]


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
            if name == "phone_home_check":
                return service.check(arguments.get("query"), arguments.get("limit", 20))
            if name == "phone_home_submit":
                return service.submit(arguments)
            if name == "phone_home_list":
                return service.list(arguments.get("query", ""), arguments.get("limit", 20), arguments.get("offset", 0))
            return service.get(arguments.get("submission_id"))
        except (ValueError, OSError, sqlite3.Error) as exc:
            error = {"error": str(exc), "status": getattr(exc, "status", 400 if isinstance(exc, ValueError) else 503)}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(error))], isError=True)

    return server


def run_mcp(service: PhoneHome) -> None:
    server = create_mcp_server(service)
    import anyio
    from mcp.server.stdio import stdio_server

    async def run() -> None:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    anyio.run(run)
