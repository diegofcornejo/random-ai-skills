#!/usr/bin/env python3
"""
Merge triage data from deepsec FileRecords into a findings.json export.

This works around https://github.com/vercel-labs/deepsec/issues/64, where
`deepsec export` does not include the `triage` field even though it's
populated in the underlying FileRecord files.

Usage:
  python3 merge-triage.py <findings.json> <files-dir> [output.json]

Arguments:
  findings.json   Path to the JSON export from `deepsec export --format json`
  files-dir       Path to the deepsec FileRecord directory
                  (typically `.deepsec/data/<project-id>/files/`)
  output.json     Optional output path. Defaults to <findings>.merged.json

If the bug is later fixed and triage is already in findings.json, this
script is a no-op and exits cleanly. Safe to run unconditionally.
"""

import json
import sys
from pathlib import Path


def collect_triage_from_filerecords(files_dir: Path) -> dict:
    """
    Walk the FileRecord directory and build a map:
        (filePath, vulnSlug) -> triage object

    Why two-key match: a single file can have multiple findings (different
    vulnSlugs), so filePath alone isn't unique. The pair (filePath, vulnSlug)
    is stable across export runs.
    """
    triage_map = {}
    record_count = 0
    triage_count = 0

    for record_path in files_dir.rglob("*.json"):
        try:
            with open(record_path) as f:
                record = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        record_count += 1

        file_path = record.get("filePath")
        if not file_path:
            continue

        for finding in record.get("findings", []):
            triage = finding.get("triage")
            if not triage:
                continue
            slug = finding.get("vulnSlug")
            if not slug:
                continue
            triage_map[(file_path, slug)] = triage
            triage_count += 1

    return {
        "map": triage_map,
        "records_scanned": record_count,
        "triages_found": triage_count,
    }


def merge(findings_path: Path, files_dir: Path) -> dict:
    """Read findings.json and inject triage from FileRecords. Returns stats."""

    with open(findings_path) as f:
        findings = json.load(f)

    if not isinstance(findings, list):
        raise ValueError(
            f"Expected JSON array at top level of {findings_path}, "
            f"got {type(findings).__name__}"
        )

    triage_data = collect_triage_from_filerecords(files_dir)
    triage_map = triage_data["map"]

    already_present = 0
    injected = 0
    no_match = 0

    for finding in findings:
        md = finding.setdefault("metadata", {})

        if md.get("triage"):
            already_present += 1
            continue

        file_path = md.get("filePath")
        slug = md.get("vulnSlug")
        if not file_path or not slug:
            no_match += 1
            continue

        triage = triage_map.get((file_path, slug))
        if triage:
            md["triage"] = triage
            injected += 1
        else:
            no_match += 1

    return {
        "findings": findings,
        "stats": {
            "total_findings": len(findings),
            "already_had_triage": already_present,
            "injected": injected,
            "no_match": no_match,
            "filerecords_scanned": triage_data["records_scanned"],
            "triages_found_in_filerecords": triage_data["triages_found"],
        },
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    findings_path = Path(sys.argv[1])
    files_dir = Path(sys.argv[2])
    output_path = (
        Path(sys.argv[3])
        if len(sys.argv) >= 4
        else findings_path.with_suffix(".merged.json")
    )

    if not findings_path.exists():
        print(f"findings.json not found: {findings_path}", file=sys.stderr)
        sys.exit(1)

    if not files_dir.exists() or not files_dir.is_dir():
        print(f"FileRecord directory not found: {files_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        result = merge(findings_path, files_dir)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Merge failed: {e}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w") as f:
        json.dump(result["findings"], f, indent=2)

    stats = result["stats"]

    if stats["injected"] == 0 and stats["already_had_triage"] == stats["total_findings"]:
        print(f"✓ All {stats['total_findings']} findings already have triage data.")
        print(f"  No merge needed. Output is identical to input.")
    elif stats["injected"] == 0 and stats["triages_found_in_filerecords"] == 0:
        print(
            f"⚠ No triage data found in FileRecords. "
            f"Has `deepsec triage` been run yet?"
        )
    else:
        print(f"✓ Merged triage data into {stats['injected']} finding(s)")
        if stats["already_had_triage"]:
            print(f"  ({stats['already_had_triage']} already had triage)")
        if stats["no_match"]:
            print(
                f"  ⚠ {stats['no_match']} finding(s) have no triage in either source"
            )
        print(f"  Scanned {stats['filerecords_scanned']} FileRecord(s)")

    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
