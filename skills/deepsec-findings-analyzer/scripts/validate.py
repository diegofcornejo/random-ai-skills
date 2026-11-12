#!/usr/bin/env python3
"""
Validate that a file is a deepsec JSON export.

Usage:
  python3 validate.py <path_to_findings.json>
  python3 validate.py <path_to_findings.json> --check-state [--data-dir <dir>]

Exits 0 on success, prints stats. Exits 1 with a descriptive error on failure.
With --check-state, also validates the sidecar (findings-status.json) shape.
"""

import json
import sys
from pathlib import Path


REQUIRED_TOP_LEVEL_KEYS = ["title", "description", "severity", "metadata"]
REQUIRED_METADATA_KEYS = ["projectId", "filePath", "severity", "vulnSlug"]
KNOWN_SEVERITIES = {"CRITICAL", "HIGH", "HIGH_BUG", "MEDIUM", "LOW", "BUG"}
KNOWN_VERDICTS = {
    "true-positive", "false-positive", "fixed", "uncertain",
    "accepted-risk",  # manual marker: real issue the team chose to live with
    "duplicate",      # same issue as another finding in the file
    None,
}
SIDECAR_STATES = {"in-progress", "wont-fix", "needs-review", "fixed-manual"}


WARNINGS: list[str] = []


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
    # Unknown enum values are a newer deepsec, not a broken file: warn, don't fail.
    unknown = severities - KNOWN_SEVERITIES
    if unknown:
        WARNINGS.append(f"unknown severity values (newer deepsec?): {sorted(map(str, unknown))}")

    # Spot-check verdicts
    verdicts = {
        f.get("metadata", {}).get("revalidation", {}).get("verdict")
        for f in data
    }
    unknown_v = verdicts - KNOWN_VERDICTS
    if unknown_v:
        WARNINGS.append(f"unknown revalidation verdicts (newer deepsec?): {sorted(map(str, unknown_v))}")

    return True, ""


def print_summary(path: str) -> None:
    with open(path) as f:
        data = json.load(f)

    severities = {}
    verdicts = {}
    for finding in data:
        sev = finding["metadata"]["severity"]
        severities[sev] = severities.get(sev, 0) + 1
        v = (finding["metadata"].get("revalidation") or {}).get("verdict") or "none"
        verdicts[v] = verdicts.get(v, 0) + 1
    resolved = sum(verdicts.get(v, 0) for v in ("fixed", "false-positive", "accepted-risk", "duplicate"))

    project_ids = {f["metadata"]["projectId"] for f in data}

    print(f"✓ Valid deepsec export")
    print(f"  Path: {path}")
    print(f"  Findings: {len(data)}")
    print(f"  Projects: {', '.join(project_ids)}")
    print(f"  Severities: {dict(severities)}")
    print(f"  Verdicts: {dict(verdicts)}")
    if resolved == 0:
        print("  Note: no resolved verdicts (fixed / false-positive / accepted-risk / duplicate).")
        print("        `deepsec export` hides them unless you pass --include-resolved.")


def validate_sidecar(sidecar_path: Path, expected_project_id: str) -> tuple[bool, str]:
    if not sidecar_path.exists():
        return True, f"(no sidecar yet at {sidecar_path})"

    try:
        with open(sidecar_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"sidecar is not valid JSON: {e}"

    if not isinstance(data, dict):
        return False, f"sidecar root is not an object (got {type(data).__name__})"

    if data.get("version") != 1:
        return False, f"sidecar version is {data.get('version')!r}, expected 1"

    if data.get("projectId") != expected_project_id:
        return False, (
            f"sidecar projectId {data.get('projectId')!r} != findings projectId "
            f"{expected_project_id!r}"
        )

    findings = data.get("findings", {})
    if not isinstance(findings, dict):
        return False, "sidecar.findings is not an object"
    for key, entry in findings.items():
        if not isinstance(entry, dict):
            return False, f"sidecar.findings[{key!r}] is not an object"
        st = entry.get("state")
        if st not in SIDECAR_STATES:
            return False, (
                f"sidecar.findings[{key!r}].state is {st!r}, "
                f"expected one of {sorted(SIDECAR_STATES)}"
            )

    sessions = data.get("sessions", [])
    if not isinstance(sessions, list):
        return False, "sidecar.sessions is not an array"
    for i, s in enumerate(sessions):
        if not isinstance(s, dict) or not s.get("sessionId") or not s.get("startedAt"):
            return False, f"sidecar.sessions[{i}] missing sessionId or startedAt"

    return True, (
        f"sidecar OK ({len(findings)} state entries, {len(sessions)} sessions)"
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="validate.py", description=__doc__)
    parser.add_argument("findings", type=Path)
    parser.add_argument("--check-state", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()

    ok, error = validate(str(args.findings))

    if not ok:
        print(f"✗ Invalid: {error}", file=sys.stderr)
        sys.exit(1)

    print_summary(str(args.findings))
    for w in WARNINGS:
        print(f"  ⚠ {w}")

    if args.check_state:
        sys.path.insert(0, str(Path(__file__).parent))
        import state as state_mod  # noqa: E402

        try:
            pid = state_mod.read_project_id(args.findings)
            sidecar_path = state_mod.resolve_sidecar_path(args.findings, args.data_dir)
        except (ValueError, FileNotFoundError) as e:
            print(f"✗ Sidecar resolution failed: {e}", file=sys.stderr)
            sys.exit(1)

        ok2, msg = validate_sidecar(sidecar_path, pid)
        if not ok2:
            print(f"✗ Sidecar invalid: {msg}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ {msg}")


if __name__ == "__main__":
    main()
