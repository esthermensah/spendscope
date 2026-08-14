"""Developer and troubleshooting command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from spendscope.app import initialize_workspace
from spendscope.branding import PRODUCT_NAME, VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spendscope", description=f"{PRODUCT_NAME} utilities")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init", help="initialize a local workspace")
    initialize.add_argument("root", type=Path)
    initialize.add_argument("--currency", default="USD")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    if args.command == "init":
        initialize_workspace(args.root, currency=args.currency)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
