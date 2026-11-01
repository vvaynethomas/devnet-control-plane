"""Installed local entrypoints; no autonomous dispatch or external model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from . import DEFAULT_DATA_DIR, DEV_NETWORK_ROOT, FACTORY_ROOT, PACKAGE_VERSION
from .phone_home import MAX_REQUEST_BYTES, PhoneHome, PhoneHomeError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devnet")
    parser.add_argument("--version", action="version", version=f"devnet {PACKAGE_VERSION}")
    parser.add_argument("--factory-root", type=Path, default=FACTORY_ROOT)
    parser.add_argument("--network-root", type=Path, default=DEV_NETWORK_ROOT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Loopback workbench, no automatic LLM evaluations")
    serve.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8780)
    commands.add_parser("mcp", help="Optional official-SDK stdio MCP server")
    phone = commands.add_parser("phone-home").add_subparsers(dest="operation", required=True)
    check = phone.add_parser("check", help="Check reusable capabilities before building")
    check.add_argument("query")
    check.add_argument("--limit", type=int, default=20)
    check.add_argument("--json", action="store_true", help="JSON is the default output")
    submit = phone.add_parser("submit", help="Append unverified discovery/tooling to the local inbox")
    submit.add_argument("--file", required=True, help="JSON request file, or - for stdin")
    intake = phone.add_parser("intake").add_subparsers(dest="intake_operation", required=True)
    listing = intake.add_parser("list")
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    for name in ("get", "export"):
        intake.add_parser(name).add_argument("id")
    phone.add_parser("rebuild", help="Explicit canonical-only Fabric refresh (no chat harvesting)")
    metabolizer = commands.add_parser(
        "metabolizer", help="Explicit opt-in repository digestion and human-only provisional review",
    ).add_subparsers(dest="metabolizer_operation", required=True)
    register = metabolizer.add_parser("register", help="Opt in a local repository; does not start scanning")
    register.add_argument("id")
    register.add_argument("path", type=Path)
    register.add_argument("--identity", required=True, help="Repository identity, e.g. owner/name; never fetched")
    register.add_argument("--revision", default="HEAD")
    register.add_argument("--exclude", action="append", default=[], help="Repository-relative path glob")
    metabolizer.add_parser("list", help="List opted-in repositories, without scanning")
    metabolizer.add_parser("unregister", help="Stop eligibility; keep historical evidence").add_argument("id")
    scan = metabolizer.add_parser("scan", help="Read a registered repository's committed revision")
    scan.add_argument("id")
    scan.add_argument("--revision", help="Explicit committed revision override, without checkout")
    metabolizer.add_parser("get", help="Read/export a persisted evidence bundle as JSON").add_argument("scan_id")
    from .digester import REVIEW_ACTIONS
    review = metabolizer.add_parser("review", help="Record human judgment only; never promote or adopt")
    review.add_argument("scan_id")
    review.add_argument("item_id")
    review.add_argument("--action", required=True, choices=REVIEW_ACTIONS)
    review.add_argument("--note", default="")
    return parser


def dispatch(service: PhoneHome, args: argparse.Namespace) -> Any:
    if args.operation == "check":
        return service.check(args.query, args.limit)
    if args.operation == "submit":
        if args.file == "-":
            raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        else:
            with Path(args.file).open("rb") as source:
                raw = source.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise PhoneHomeError("submission exceeds 64 KiB", 413)
        return service.submit(json.loads(raw.decode("utf-8")))
    if args.operation == "rebuild":
        if not service.factory_root.is_dir():
            raise PhoneHomeError("canonical source directory unavailable", 503)
        counts = service.fabric.rebuild(include_conversations=False)
        return {"counts": counts, "fabric": service.fabric.freshness()}
    if args.intake_operation == "list":
        return service.list(args.query, args.limit, args.offset)
    return service.get(args.id)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "metabolizer":
            from .repo_metabolizer import RepositoryMetabolizer
            metabolizer = RepositoryMetabolizer(args.data_dir, args.factory_root)
            operation = args.metabolizer_operation
            if operation == "register":
                result = metabolizer.register(args.id, args.path, args.identity, args.revision, args.exclude)
            elif operation == "list":
                result = metabolizer.repositories()
            elif operation == "unregister":
                result = metabolizer.unregister(args.id)
            elif operation == "scan":
                result = metabolizer.scan(args.id, args.revision)
            elif operation == "get":
                result = metabolizer.get(args.scan_id)
            else:
                result = metabolizer.review(args.scan_id, args.item_id, args.action, args.note)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0
        service = PhoneHome(args.factory_root, args.network_root, args.data_dir)
        if args.command == "serve":
            from .ui import ControlPlaneWorkbench, serve_control_plane
            wb = ControlPlaneWorkbench(args.factory_root, args.network_root, args.data_dir)
            server = serve_control_plane(args.host, args.port, workbench=wb, seed_evaluation=False)
            print(f"DNCP listening on http://127.0.0.1:{server.server_port}/", file=sys.stderr)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        elif args.command == "mcp":
            from .mcp_server import run_mcp
            run_mcp(service)
        else:
            print(json.dumps(dispatch(service, args), indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, sqlite3.Error, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc), "status": getattr(exc, "status", 503)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
