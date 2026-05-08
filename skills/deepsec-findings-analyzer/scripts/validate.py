#!/usr/bin/env python3
"""
Validate that a file is a deepsec JSON export.

Usage: python3 validate.py <path_to_findings.json>

Exits 0 on success, prints stats. Exits 1 with a descriptive error on failure.
"""

import json
import sys
from pathlib import Path


REQUIRED_TOP_LEVEL_KEYS = ["title", "description", "severity", "metadata"]
REQUIRED_METADATA_KEYS = ["projectId", "filePath", "severity", "vulnSlug"]
KNOWN_SEVERITIES = {"CRITICAL", "HIGH", "HIGH_BUG", "MEDIUM", "LOW", "BUG"}
KNOWN_VERDICTS = {"true-positive", "false-positive", "fixed", "uncertain", None}


def validate(path: str) -> tuple[bool, str]:
    p = Path(path)

    if not p.exists():
        return False, f"File not found: {path}"

    if not p.is_file():
        return False, f"Not a file: {path}"

    if p.stat().st_size == 0:
        return False, f"File is empty: {path}"

    try:
        with open(p) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Not valid JSON: {e}"

    if not isinstance(data, list):
        return False, f"Expected JSON array at top level, got {type(data).__name__}"

    if len(data) == 0:
        return False, "JSON array is empty (no findings)"

    # Validate first finding has expected shape
    first = data[0]
    if not isinstance(first, dict):
        return False, f"Expected objects in array, got {type(first).__name__}"

    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in first]
    if missing:
        return False, f"First finding missing required keys: {missing}"

    md = first.get("metadata", {})
    missing_md = [k for k in REQUIRED_METADATA_KEYS if k not in md]
    if missing_md:
        return False, f"First finding's metadata missing required keys: {missing_md}"

    # Spot-check severities
    severities = {f.get("metadata", {}).get("severity") for f in data}
    unknown = severities - KNOWN_SEVERITIES
    if unknown:
        return False, f"Unknown severity values found: {unknown}"

    # Spot-check verdicts
    verdicts = {
        f.get("metadata", {}).get("revalidation", {}).get("verdict")
        for f in data
    }
    unknown_v = verdicts - KNOWN_VERDICTS
    if unknown_v:
        return False, f"Unknown revalidation verdicts found: {unknown_v}"

    return True, ""


def print_summary(path: str) -> None:
    with open(path) as f:
        data = json.load(f)

    severities = {}
    for finding in data:
        sev = finding["metadata"]["severity"]
        severities[sev] = severities.get(sev, 0) + 1

    project_ids = {f["metadata"]["projectId"] for f in data}

    print(f"✓ Valid deepsec export")
    print(f"  Path: {path}")
    print(f"  Findings: {len(data)}")
    print(f"  Projects: {', '.join(project_ids)}")
    print(f"  Severities: {dict(severities)}")


def main():
    if len(sys.argv) != 2:
        print("Usage: validate.py <path_to_findings.json>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    ok, error = validate(path)

    if not ok:
        print(f"✗ Invalid: {error}", file=sys.stderr)
        sys.exit(1)

    print_summary(path)


if __name__ == "__main__":
    main()
