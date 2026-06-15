from __future__ import annotations

import argparse

from data_checks.runner import run_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CompanyLens data source checks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-all", help="Run all configured data source checks")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run-all":
        return run_all()

    parser.error(f"Unsupported command: {args.command}")
    return 2
