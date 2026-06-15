from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_checks.models import CheckResult


def build_report(results: list[CheckResult]) -> dict[str, Any]:
    counts = Counter(result.status for result in results)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "summary": {
            "total": len(results),
            "passed": counts.get("passed", 0),
            "warning": counts.get("warning", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        },
        "results": [result.as_dict() for result in results],
    }


def write_report(report: dict[str, Any], reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"data-checks-{timestamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def print_summary(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    print("Data source checks complete")
    print(
        "Summary: "
        f"{summary['passed']} passed, "
        f"{summary['warning']} warning, "
        f"{summary['failed']} failed, "
        f"{summary['skipped']} skipped "
        f"({summary['total']} total)"
    )
    print(f"Report: {path}")

    notable = [
        result
        for result in report["results"]
        if result["status"] in {"failed", "warning", "skipped"}
    ]
    if notable:
        print()
        print("Notable results:")
        for result in notable[:20]:
            owner = ""
            if result.get("ticker"):
                owner = f" [{result['ticker']}]"
            print(
                f"- {result['status'].upper()} {result['source']}/{result['check']}"
                f"{owner}: {result['message']}"
            )
        if len(notable) > 20:
            print(f"- ... {len(notable) - 20} more notable results in JSON report")
