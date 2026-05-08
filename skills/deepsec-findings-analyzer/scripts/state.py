#!/usr/bin/env python3
"""
Sidecar state management for deepsec-findings-analyzer.

The skill is multi-session. deepsec stores native verdicts in
`metadata.revalidation.verdict` (true-positive, false-positive, fixed,
uncertain), but it has no concept of human-curated states like
"in-progress" or "wont-fix". This script manages those gap states in a
sidecar JSON file at:

    <deepsec data dir>/<projectId>/findings-status.json

Native verdicts always win when computing the effective state — the
sidecar is only consulted when no native verdict exists (or it's
"uncertain"). This way `deepsec revalidate` remains the source of truth
for fixed/false-positive determinations (it verifies via git history).

Schema (version 1):

    {
      "version": 1,
      "projectId": "...",
      "lastUpdated": "ISO8601",
      "findings": {
        "<filePath>::<vulnSlug>::<firstLine>": {
          "state": "in-progress" | "wont-fix" | "needs-review" | "fixed-manual",
          "stateSetAt": "ISO8601"
        }
      },
      "sessions": [
        {
          "sessionId": "<YYYYMMDDHHMMSS>-<rand4>",
          "startedAt": "ISO8601",
          "endedAt": "ISO8601 or null",
          "decisions": [
            {"key": "...", "from": "...", "to": "...", "at": "ISO8601"}
          ],
          "summary": "free-form one-liner from the skill"
        }
      ]
    }

Usage (subcommands):

    state.py path <findings.json> [--data-dir <dir>]
        Print resolved sidecar path. Creates parent dirs if missing.

    state.py load <findings.json> [--data-dir <dir>]
        Print sidecar JSON. Empty schema if file missing.

    state.py effective <findings.json> [--data-dir <dir>]
        Print {key: effective_state} mapping for every finding.

    state.py summary <findings.json> [--data-dir <dir>] [--json]
        Print effective state distribution + last-session info.

    state.py mark <findings.json> <key> <state> [--session <id>] [--data-dir <dir>]
        Set sidecar state for a finding. If --session given, append the
        decision to that session. State must be one of: in-progress,
        wont-fix, needs-review, fixed-manual, none (clears).

    state.py session-open <findings.json> [--data-dir <dir>]
        Open a new session entry, print its sessionId on stdout.

    state.py session-close <findings.json> <sessionId> [--summary "..."] [--data-dir <dir>]
        Close a session by setting endedAt and (optionally) summary.

    state.py orphans <findings.json> [--data-dir <dir>]
        List sidecar finding keys with no matching finding in findings.json.
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
VALID_STATES = {"in-progress", "wont-fix", "needs-review", "fixed-manual"}
NATIVE_TERMINAL_VERDICTS = {"fixed", "false-positive"}
SIDECAR_FILENAME = "findings-status.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = f"{random.randint(0, 0xFFFF):04x}"
    return f"{ts}-{rand}"


def finding_key(finding: dict) -> str:
    md = finding.get("metadata", {})
    file_path = md.get("filePath", "")
    slug = md.get("vulnSlug", "")
    lines = finding.get("lineNumbers") or md.get("lineNumbers") or [0]
    first = lines[0] if lines else 0
    return f"{file_path}::{slug}::{first}"


def resolve_sidecar_path(findings_path: Path, data_dir: Path | None) -> Path:
    """
    Resolution order:
      1. If --data-dir given, use <data-dir>/<projectId>/findings-status.json.
      2. Walk likely deepsec layouts to find data/<projectId>/.
      3. Fallback to <findings.json parent>/findings-status.json.
    """
    project_id = read_project_id(findings_path)

    if data_dir is not None:
        return data_dir / project_id / SIDECAR_FILENAME

    parent = findings_path.parent.resolve()
    candidates = [
        parent / "data" / project_id,
        parent / ".deepsec" / "data" / project_id,
        Path.cwd() / "data" / project_id,
        Path.cwd() / ".deepsec" / "data" / project_id,
        parent.parent / "data" / project_id,
    ]
    for c in candidates:
        if c.is_dir():
            return c / SIDECAR_FILENAME

    print(
        f"warning: deepsec data dir not found for project '{project_id}'; "
        f"using fallback at {parent / SIDECAR_FILENAME}",
        file=sys.stderr,
    )
    return parent / SIDECAR_FILENAME


def read_project_id(findings_path: Path) -> str:
    with open(findings_path) as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{findings_path} is not a non-empty JSON array")
    pid = data[0].get("metadata", {}).get("projectId")
    if not pid:
        raise ValueError(f"first finding in {findings_path} has no metadata.projectId")
    return pid


def empty_sidecar(project_id: str) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "projectId": project_id,
        "lastUpdated": now_iso(),
        "findings": {},
        "sessions": [],
    }


def load_sidecar(path: Path, project_id: str) -> dict:
    if not path.exists():
        return empty_sidecar(project_id)
    with open(path) as f:
        data = json.load(f)
    if data.get("version") != SCHEMA_VERSION:
        raise ValueError(
            f"sidecar at {path} has version {data.get('version')!r}, "
            f"expected {SCHEMA_VERSION}"
        )
    if data.get("projectId") != project_id:
        raise ValueError(
            f"sidecar projectId {data.get('projectId')!r} != findings projectId {project_id!r}"
        )
    data.setdefault("findings", {})
    data.setdefault("sessions", [])
    return data


def save_sidecar(path: Path, sidecar: dict) -> None:
    sidecar["lastUpdated"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(sidecar, f, indent=2)
    os.replace(tmp, path)


def native_verdict(finding: dict) -> str | None:
    return finding.get("metadata", {}).get("revalidation", {}).get("verdict")


def effective_state(finding: dict, sidecar_entry: dict | None) -> str:
    """
    Precedence:
      1. Native fixed / false-positive → "native:<verdict>"
      2. Sidecar state if present
      3. Native true-positive → "native:true-positive"
      4. Native uncertain → "uncertain"
      5. Otherwise → "unreviewed"
    """
    verdict = native_verdict(finding)
    if verdict in NATIVE_TERMINAL_VERDICTS:
        return f"native:{verdict}"
    if sidecar_entry and sidecar_entry.get("state") in VALID_STATES:
        return sidecar_entry["state"]
    if verdict == "true-positive":
        return "native:true-positive"
    if verdict == "uncertain":
        return "uncertain"
    return "unreviewed"


def build_effective_map(findings: list, sidecar: dict) -> dict:
    by_key = sidecar.get("findings", {})
    out = {}
    for f in findings:
        key = finding_key(f)
        out[key] = effective_state(f, by_key.get(key))
    return out


def find_session(sidecar: dict, session_id: str) -> dict | None:
    for s in sidecar.get("sessions", []):
        if s.get("sessionId") == session_id:
            return s
    return None


# ---------- CLI ----------


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("findings", type=Path, help="Path to findings.json")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override deepsec data directory (sidecar lives at <data-dir>/<projectId>/findings-status.json)",
    )


def cmd_path(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    print(p)
    return 0


def cmd_load(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)
    print(json.dumps(sidecar, indent=2))
    return 0


def cmd_effective(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)
    with open(args.findings) as f:
        findings = json.load(f)
    print(json.dumps(build_effective_map(findings, sidecar), indent=2))
    return 0


def cmd_summary(args) -> int:
    from collections import Counter

    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)
    with open(args.findings) as f:
        findings = json.load(f)

    eff = build_effective_map(findings, sidecar)
    dist = Counter(eff.values())
    sessions = sidecar.get("sessions", [])
    last = sessions[-1] if sessions else None

    summary = {
        "sidecar_path": str(p),
        "sidecar_exists": p.exists(),
        "total_findings": len(findings),
        "effective_state_distribution": dict(dist),
        "session_count": len(sessions),
        "last_session": last,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"Sidecar:   {p}")
    print(f"Exists:    {p.exists()}")
    print(f"Findings:  {len(findings)}")
    print()
    print("Effective state distribution:")
    for state, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {state}: {n}")
    print()
    print(f"Sessions logged: {len(sessions)}")
    if last:
        print(f"Last session:    {last['sessionId']}")
        print(f"  Started:       {last.get('startedAt')}")
        print(f"  Ended:         {last.get('endedAt') or '(open)'}")
        print(f"  Decisions:     {len(last.get('decisions', []))}")
        if last.get("summary"):
            print(f"  Summary:       {last['summary']}")
    return 0


def cmd_mark(args) -> int:
    if args.state != "none" and args.state not in VALID_STATES:
        print(
            f"error: state must be one of {sorted(VALID_STATES)} or 'none' (clears)",
            file=sys.stderr,
        )
        return 2

    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)

    findings_index = {finding_key(f): f for f in json.load(open(args.findings))}
    if args.key not in findings_index:
        print(
            f"error: key {args.key!r} not found in findings.json",
            file=sys.stderr,
        )
        return 1

    entries = sidecar.setdefault("findings", {})
    prev = entries.get(args.key, {}).get("state")

    if args.state == "none":
        entries.pop(args.key, None)
        new = None
    else:
        entries[args.key] = {"state": args.state, "stateSetAt": now_iso()}
        new = args.state

    if args.session:
        sess = find_session(sidecar, args.session)
        if sess is None:
            print(
                f"error: session {args.session!r} not found in sidecar",
                file=sys.stderr,
            )
            return 1
        sess.setdefault("decisions", []).append(
            {"key": args.key, "from": prev, "to": new, "at": now_iso()}
        )

    save_sidecar(p, sidecar)
    print(f"✓ {args.key}: {prev or '∅'} → {new or '∅'}")
    return 0


def cmd_session_open(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)

    sid = new_session_id()
    sidecar.setdefault("sessions", []).append(
        {
            "sessionId": sid,
            "startedAt": now_iso(),
            "endedAt": None,
            "decisions": [],
            "summary": None,
        }
    )
    save_sidecar(p, sidecar)
    print(sid)
    return 0


def cmd_session_close(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)

    sess = find_session(sidecar, args.session_id)
    if sess is None:
        print(f"error: session {args.session_id!r} not found", file=sys.stderr)
        return 1

    sess["endedAt"] = now_iso()
    if args.summary:
        sess["summary"] = args.summary
    save_sidecar(p, sidecar)
    print(f"✓ closed {args.session_id} ({len(sess.get('decisions', []))} decisions)")
    return 0


def cmd_orphans(args) -> int:
    p = resolve_sidecar_path(args.findings, args.data_dir)
    pid = read_project_id(args.findings)
    sidecar = load_sidecar(p, pid)

    with open(args.findings) as f:
        findings = json.load(f)
    live_keys = {finding_key(x) for x in findings}
    orphans = sorted(set(sidecar.get("findings", {})) - live_keys)

    print(json.dumps({"sidecar_path": str(p), "orphans": orphans}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="state.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_path = sub.add_parser("path", help="Print resolved sidecar path")
    add_common(sp_path)
    sp_path.set_defaults(func=cmd_path)

    sp_load = sub.add_parser("load", help="Print sidecar JSON")
    add_common(sp_load)
    sp_load.set_defaults(func=cmd_load)

    sp_eff = sub.add_parser("effective", help="Print {key: effective_state} map")
    add_common(sp_eff)
    sp_eff.set_defaults(func=cmd_effective)

    sp_sum = sub.add_parser("summary", help="Show effective state distribution and last session")
    add_common(sp_sum)
    sp_sum.add_argument("--json", action="store_true")
    sp_sum.set_defaults(func=cmd_summary)

    sp_mark = sub.add_parser("mark", help="Set sidecar state for a finding")
    add_common(sp_mark)
    sp_mark.add_argument("key", help="Finding key (filePath::vulnSlug::firstLine)")
    sp_mark.add_argument("state", help=f"One of: {sorted(VALID_STATES)} or 'none'")
    sp_mark.add_argument("--session", help="Session id to record this decision under")
    sp_mark.set_defaults(func=cmd_mark)

    sp_so = sub.add_parser("session-open", help="Open a new session entry")
    add_common(sp_so)
    sp_so.set_defaults(func=cmd_session_open)

    sp_sc = sub.add_parser("session-close", help="Close a session entry")
    add_common(sp_sc)
    sp_sc.add_argument("session_id")
    sp_sc.add_argument("--summary", default=None)
    sp_sc.set_defaults(func=cmd_session_close)

    sp_orph = sub.add_parser("orphans", help="List sidecar keys not in current findings")
    add_common(sp_orph)
    sp_orph.set_defaults(func=cmd_orphans)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
