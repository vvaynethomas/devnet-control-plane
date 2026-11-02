"""Installed local entrypoints; no autonomous dispatch or external model calls."""

from __future__ import annotations

import argparse
import base64
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
    digest = commands.add_parser("digest", help="Opt-in read-only repository evidence; no automatic phone-home").add_subparsers(
        dest="digest_operation", required=True,
    )
    for name in ("register", "disable", "scan"):
        sub = digest.add_parser(name)
        sub.add_argument("repository", type=Path)
        if name == "scan":
            sub.add_argument("--target", default="", help="Optional focus; notable untargeted material is retained as residue")
            sub.add_argument("--revision", default="HEAD", help="Committed revision to read; resolved once without checkout or fetch")
    digest.add_parser("list")
    phone = commands.add_parser("phone-home").add_subparsers(dest="operation", required=True)
    check = phone.add_parser("check", help="Check reusable capabilities before building")
    check.add_argument("query")
    check.add_argument("--limit", type=int, default=20)
    check.add_argument("--json", action="store_true", help="JSON is the default output")
    submit = phone.add_parser("submit", help="Append unverified discovery/tooling to the local inbox")
    submit.add_argument("--file", required=True, help="JSON request file, or - for stdin")
    ingest = phone.add_parser("ingest", help="Digest and ingest explicitly supplied local material in one submission")
    ingest.add_argument("file", type=Path)
    ingest.add_argument("--format", choices=("text", "markdown", "csv", "html", "python", "zip"))
    ingest.add_argument("--identity", default=None, help="Original source identity; defaults to the explicit local path")
    ingest.add_argument("--target", default="")
    ingest.add_argument("--source-ref", default="")
    ingest.add_argument("--source-session", default="")
    ingest.add_argument("--idempotency-key", default="")
    intake = phone.add_parser("intake").add_subparsers(dest="intake_operation", required=True)
    listing = intake.add_parser("list")
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    for name in ("get", "export"):
        intake.add_parser(name).add_argument("id")
    phone.add_parser("rebuild", help="Explicit canonical-only Fabric refresh (no chat harvesting)")
    return parser


def dispatch(service: PhoneHome, args: argparse.Namespace) -> Any:
    if args.operation == "ingest":
        from .material_ingestion import EXTENSIONS, MAX_INPUT_BYTES
        with args.file.open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise PhoneHomeError("material exceeds 32 KiB", 413)
        return service.submit({
            "kind": "material",
            "material": {"name": args.file.name, "format": args.format or EXTENSIONS.get(args.file.suffix.lower()),
                         "identity": args.identity if args.identity is not None else str(args.file.absolute()),
                         "base64": base64.b64encode(raw).decode("ascii")},
            "target": args.target, "source_ref": args.source_ref, "source_session": args.source_session,
            "idempotency_key": args.idempotency_key,
        })
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
        if args.command == "digest":
            from .repo_metabolizer import RepositoryMetabolizer
            from .fabric import FabricIndex
            digester = RepositoryMetabolizer(
                args.data_dir, FabricIndex(args.data_dir / "control_plane_fabric.sqlite", args.factory_root),
            )
            if args.digest_operation == "list":
                output = digester.registrations()
            elif args.digest_operation == "register":
                output = digester.register(args.repository)
            elif args.digest_operation == "disable":
                output = digester.disable(args.repository)
            else:
                output = digester.scan(args.repository, args.target, args.revision)
            print(json.dumps(output, indent=2, ensure_ascii=False))
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
