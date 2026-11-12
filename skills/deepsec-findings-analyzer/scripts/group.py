#!/usr/bin/env python3
"""
Group deepsec findings by various criteria.

Usage:
  python3 group.py <path> --by slug-module      # group by vulnSlug + module path (default)
  python3 group.py <path> --by file             # group by filePath
  python3 group.py <path> --by slug             # group by vulnSlug only
  python3 group.py <path> --by severity         # group by severity
  python3 group.py <path> --by module           # group by module path

Add --json for machine-readable output.
Add --min-size N to only include groups with N+ findings (default: 1).
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def get_module(path: str) -> str:
    """Extract module path. Handles common monorepo layouts."""
    parts = path.split("/")

    # Look for "modules/" segment (common in NestJS/Express patterns)
    if "modules" in parts:
        idx = parts.index("modules")
        if idx + 1 < len(parts):
            return f"modules/{parts[idx + 1]}"

    # Look for app/api or apps/api/src segment
    for marker in ("apps", "packages"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 2 < len(parts):
                return "/".join(parts[idx : idx + 3])

    # Fallback: first 3 segments
    return "/".join(parts[:3])


def group_findings(findings: list, by: str) -> dict:
    """Group findings by the specified criterion."""

    groups = defaultdict(list)

    for f in findings:
        md = f["metadata"]
        if by == "slug-module":
            key = f"{md['vulnSlug']} in {get_module(md['filePath'])}"
        elif by == "file":
            key = md["filePath"]
        elif by == "slug":
            key = md["vulnSlug"]
        elif by == "severity":
            key = md["severity"]
        elif by == "module":
            key = get_module(md["filePath"])
        else:
            raise ValueError(f"Unknown grouping: {by}")

        groups[key].append(
            {
                # `deepsec export` prefixes titles with "[SEVERITY] "; severity is shown separately.
                "title": re.sub(r"^\[[A-Z_]+\]\s*", "", f["title"]),
                "path": md["filePath"],
                "lineNumbers": md.get("lineNumbers", []),
                "severity": md["severity"],
                "vulnSlug": md["vulnSlug"],
                "confidence": md.get("confidence", "unknown"),
                "verdict": md.get("revalidation", {}).get("verdict"),
            }
        )

    return dict(groups)


def severity_rank(sev: str) -> int:
    """Higher = more severe. Used for sorting groups."""
    order = {
        "CRITICAL": 5,
        "HIGH": 4,
        "HIGH_BUG": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "BUG": 0,
    }
    return order.get(sev, 0)


def max_severity(items: list) -> str:
    """Find the highest severity in a group."""
    return max((i["severity"] for i in items), key=severity_rank)


def print_human(groups: dict, min_size: int = 1) -> None:
    """Print groups, sorted by max severity then size."""
    sorted_groups = sorted(
        groups.items(),
        key=lambda x: (-severity_rank(max_severity(x[1])), -len(x[1])),
    )

    for key, items in sorted_groups:
        if len(items) < min_size:
            continue

        max_sev = max_severity(items)
        print(f"=== {key} ({len(items)} findings, max severity: {max_sev}) ===")
        for i in items:
            line_part = ""
            if i["lineNumbers"]:
                line_part = f" lines {','.join(str(l) for l in i['lineNumbers'][:3])}"
                if len(i["lineNumbers"]) > 3:
                    line_part += f"+{len(i['lineNumbers']) - 3}"
            print(
                f"  [{i['severity']}/{i['confidence']}] {i['title']}"
            )
            print(f"    {i['path']}{line_part}")
            if i["verdict"] and i["verdict"] != "true-positive":
                print(f"    Verdict: {i['verdict']}")
        print()


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    by = "slug-module"
    output_json = False
    min_size = 1

    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--by" and i + 1 < len(sys.argv):
            by = sys.argv[i + 1]
        elif arg == "--json":
            output_json = True
        elif arg == "--min-size" and i + 1 < len(sys.argv):
            min_size = int(sys.argv[i + 1])

    if not Path(path).exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        findings = json.load(f)

    groups = group_findings(findings, by)

    if output_json:
        # Filter by min_size
        filtered = {k: v for k, v in groups.items() if len(v) >= min_size}
        print(json.dumps(filtered, indent=2))
    else:
        print_human(groups, min_size=min_size)


if __name__ == "__main__":
    main()
