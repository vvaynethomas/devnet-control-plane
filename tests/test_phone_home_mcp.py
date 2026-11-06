"""Official MCP client/server protocol parity on a synthetic local fixture."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_phone_home as fixtures
from test_operational_handoffs import example_packet, example_result


class TestPhoneHomeMCP(unittest.TestCase):
    setUp = fixtures.TestPhoneHome.setUp

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP extra is not installed")
    def test_real_stdio_negotiation_tools_parity_and_errors(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def exercise() -> None:
            args = ["-m", "control_plane.cli", "--factory-root", str(self.factory),
                    "--network-root", str(self.network), "--data-dir", str(self.data), "mcp"]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=self.root)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "devnet-phone-home")
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {
                        "phone_home_check", "phone_home_submit", "phone_home_list", "phone_home_get",
                        "handoff_submit", "handoff_result", "handoff_get", "handoff_list",
                    })
                    await session.send_ping()
                    checked = await session.call_tool("phone_home_check", {"query": "sqlite"})
                    self.assertFalse(checked.isError)
                    output = checked.structuredContent
                    self.assertEqual(output["decision_ladder"], self.service.check("sqlite")["decision_ladder"])
                    submitted = await session.call_tool("phone_home_submit", self.payload)
                    self.assertFalse(submitted.isError)
                    receipt = submitted.structuredContent
                    self.assertEqual(receipt, self.service.get(receipt["id"]))
                    exported = await session.call_tool("phone_home_get", {"submission_id": receipt["id"]})
                    self.assertEqual(exported.structuredContent, receipt)
                    listing = await session.call_tool("phone_home_list", {"limit": 1})
                    self.assertEqual(listing.structuredContent["total"], 1)
                    material = await session.call_tool("phone_home_submit", {
                        "kind": "material", "material": {"name": "note.md", "format": "markdown",
                                                       "text": "# Topic\nGoal: reuse"},
                    })
                    self.assertFalse(material.isError)
                    self.assertTrue(material.structuredContent["review"]["ingested"])
                    self.assertFalse(material.structuredContent["review"]["acceptance_required"])
                    self.assertEqual(material.structuredContent, self.service.get(material.structuredContent["id"]))
                    for tool, arguments in [
                        ("phone_home_check", {"query": ""}),
                        ("phone_home_check", {"query": "sqlite", "limit": 51}),
                        ("phone_home_check", {"query": "sqlite", "limit": True}),
                        ("phone_home_submit", {**self.payload, "schema_version": True}),
                        ("phone_home_submit", {**self.payload, "status": "approved"}),
                        ("phone_home_submit", {**self.payload, "kind": "approved"}),
                        ("phone_home_get", {"submission_id": "INTAKE-missing"}),
                        ("unknown_tool", {}),
                    ]:
                        failure = await session.call_tool(tool, arguments)
                        self.assertTrue(failure.isError)
                    self.assertEqual(self.service.list()["total"], 2)
        asyncio.run(exercise())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP extra is not installed")
    def test_real_stdio_operational_handoff_loop(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def exercise() -> None:
            args = ["-m", "control_plane.cli", "--factory-root", str(self.factory),
                    "--network-root", str(self.network), "--data-dir", str(self.data), "mcp"]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=self.root)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    packet = example_packet()
                    submitted = await session.call_tool("handoff_submit", packet)
                    self.assertFalse(submitted.isError)
                    duplicate = await session.call_tool("handoff_submit", packet)
                    self.assertEqual(submitted.structuredContent, duplicate.structuredContent)
                    pending = await session.call_tool("handoff_list", {"recipient": packet["recipient"]})
                    self.assertEqual(pending.structuredContent["total"], 1)
                    result = await session.call_tool("handoff_result", example_result())
                    self.assertFalse(result.isError)
                    detail = await session.call_tool("handoff_get", {"handoff_id": packet["handoff_id"]})
                    self.assertEqual(detail.structuredContent, self.service.handoff_get(packet["handoff_id"]))
                    self.assertEqual(detail.structuredContent["result"], result.structuredContent)
                    info = {**packet, "mode": "information", "handoff_id": "mcp-info"}
                    del info["requested_action"]
                    self.assertFalse((await session.call_tool("handoff_submit", info)).isError)
                    pending = await session.call_tool("handoff_list", {})
                    self.assertEqual(pending.structuredContent["total"], 1)
                    for tool, arguments in [
                        ("handoff_submit", {**packet, "context_snapshot": "conflict"}),
                        ("handoff_submit", {**packet, "authority": "approved"}),
                        ("handoff_result", {**example_result(), "summary": "conflict"}),
                        ("handoff_result", {**example_result(), "outcome": "approved"}),
                        ("handoff_result", {**example_result(), "handoff_id": "missing", "result_id": "missing"}),
                        ("handoff_get", {"handoff_id": "missing"}),
                        ("handoff_get", {}),
                        ("handoff_list", {"limit": True}),
                        ("handoff_submit", {**packet, "context_snapshot": "ghp_" + "a" * 30}),
                    ]:
                        failure = await session.call_tool(tool, arguments)
                        self.assertTrue(failure.isError, tool)
                        self.assertNotIn("ghp_", str(failure))
                    self.assertEqual(self.service.list()["total"], 3)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    reloaded = await session.call_tool("handoff_get", {"handoff_id": example_packet()["handoff_id"]})
                    self.assertFalse(reloaded.isError)
                    self.assertEqual(reloaded.structuredContent["state"], "blocked")
                    self.assertEqual(reloaded.structuredContent["result"]["summary"], example_result()["summary"])
        asyncio.run(exercise())

    def test_missing_optional_dependency_is_actionable(self) -> None:
        from control_plane.mcp_server import create_mcp_server
        with patch.dict(sys.modules, {"mcp": None, "mcp.server": None, "mcp.server.fastmcp": None}):
            with self.assertRaisesRegex(RuntimeError, "MCP extra missing"):
                create_mcp_server(self.service)


if __name__ == "__main__":
    unittest.main()
