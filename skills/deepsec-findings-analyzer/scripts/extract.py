#!/usr/bin/env python3
"""
Print selected findings from a deepsec export, compact and without people data.

Used by the Level 3 verification protocol (and handy for drill-down): a
worker reads only the findings it must verify instead of the whole export.

Usage:
  python3 extract.py <findings.json> --key KEY [--key KEY ...]
  python3 extract.py <findings.json> --file PATH [--slug SLUG]
  python3 extract.py <findings.json> --list-keys [--min-severity HIGH]

KEY is the state key `<filePath>::<vulnSlug>::<firstLineNumber>` (state.py).
Output (stdout): JSON {"findings": [...], "missing_keys": [...], "project_id",
"source_root"}. source_root is deepsec's `rootPath` from
.deepsec/data/<projectId>/project.json when found near the export, else null. Each finding
keeps key, title, severity, confidence, vulnSlug, filePath, lineNumbers,
description (without the Owners / Top contributors / Recent committers
sections), revalidation and triage. Exit 1 if nothing matched.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY_ORDER = ["CRITICAL", "HIGH", "HIGH_BUG", "MEDIUM", "BUG", "LOW"]
PEOPLE_SECTIONS = re.compile(
    r"^## (Owners|Top contributors|Recent committers[^\n]*)\n[\s\S]*?(?=^## |\Z)", re.MULTILINE
)
SEV_PREFIX = re.compile(r"^\[[A-Z_]+\]\s*")


def finding_key(f: dict) -> str:
    md = f.get("metadata", {})
    lines = md.get("lineNumbers") or f.get("lineNumbers") or [0]
    return f"{md.get('filePath', '')}::{md.get('vulnSlug', '')}::{lines[0] if lines else 0}"


def find_source_root(findings_path: Path, project_id: str):
    """deepsec's rootPath for this project, looked up near the export (or None)."""
    base = findings_path.resolve().parent
    for d in (base, base.parent, Path.cwd()):
        for data in (d / ".deepsec" / "data", d / "data"):
            pj = data / project_id / "project.json"
            if pj.is_file():
                try:
                    return json.loads(pj.read_text()).get("rootPath")
                except (OSError, json.JSONDecodeError):
                    return None
    return None


def compact(f: dict) -> dict:
    md = f.get("metadata", {})
    out = {
        "key": finding_key(f),
        "title": SEV_PREFIX.sub("", f.get("title", "")),
        "severity": md.get("severity") or f.get("severity"),
        "confidence": md.get("confidence"),
        "vulnSlug": md.get("vulnSlug"),
        "filePath": md.get("filePath"),
        "lineNumbers": md.get("lineNumbers", []),
        "description": re.sub(r"\n{3,}", "\n\n", PEOPLE_SECTIONS.sub("", f.get("description", ""))).strip(),
    }
    if md.get("revalidation"):
        out["revalidation"] = md["revalidation"]
    if md.get("triage"):
        out["triage"] = {k: md["triage"].get(k) for k in ("priority", "exploitability", "impact", "reasoning")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="extract.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings", type=Path)
    ap.add_argument("--key", action="append", default=[])
    ap.add_argument("--file")
    ap.add_argument("--slug")
    ap.add_argument("--list-keys", action="store_true")
    ap.add_argument("--min-severity", choices=SEVERITY_ORDER)
    args = ap.parse_args()

    data = json.loads(args.findings.read_text())
    if not isinstance(data, list):
        print("error: expected a JSON array (deepsec export --format json)", file=sys.stderr)
        return 1

    if args.min_severity:
        allowed = set(SEVERITY_ORDER[: SEVERITY_ORDER.index(args.min_severity) + 1])
        data = [f for f in data if f.get("metadata", {}).get("severity") in allowed]

    if args.list_keys:
        for f in data:
            md = f.get("metadata", {})
            print(f"{finding_key(f)}\t{md.get('severity')}\t{SEV_PREFIX.sub('', f.get('title', ''))}")
        return 0

    if not (args.key or args.file):
        ap.error("give --key, --file, or --list-keys")

    by_key = {finding_key(f): f for f in data}
    selected, missing = [], []
    for k in args.key:
        if k in by_key:
            selected.append(by_key[k])
        else:
            missing.append(k)
    if args.file:
        for f in data:
            md = f.get("metadata", {})
            if md.get("filePath") == args.file and (not args.slug or md.get("vulnSlug") == args.slug):
                if f not in selected:
                    selected.append(f)

    project_id = (data[0].get("metadata", {}).get("projectId") if data else None) or ""
    json.dump({"findings": [compact(f) for f in selected], "missing_keys": missing,
               "project_id": project_id,
               "source_root": find_source_root(args.findings, project_id) if project_id else None},
              sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if selected else 1


if __name__ == "__main__":
    sys.exit(main())
