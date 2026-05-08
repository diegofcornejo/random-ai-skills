#!/usr/bin/env python3
"""
Compute deterministic statistics from a deepsec findings export.

Usage: python3 stats.py <path_to_findings.json> [--json] [--state] [--data-dir <dir>]

Outputs human-readable stats by default, JSON with --json flag.

With --state, also loads the sidecar (findings-status.json) and reports
effective_state distribution (sidecar state merged with deepsec native
verdicts via state.py's precedence rules). Use --data-dir to override the
deepsec data directory location.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state as state_mod  # noqa: E402


def compute_stats(findings: list, sidecar: dict | None = None) -> dict:
    """Compute all the stats Level 1 needs.

    If `sidecar` is provided, also computes effective_state_distribution
    (sidecar state merged with native verdicts) and last-session info.
    """

    total = len(findings)

    # Severity distribution
    severity = Counter(f["metadata"]["severity"] for f in findings)

    # Confidence distribution
    confidence = Counter(
        f["metadata"].get("confidence", "unknown") for f in findings
    )

    # Vuln slug distribution
    slugs = Counter(f["metadata"]["vulnSlug"] for f in findings)

    # Revalidation verdicts
    verdicts = Counter(
        f["metadata"].get("revalidation", {}).get("verdict") or "none"
        for f in findings
    )

    # Project IDs
    projects = sorted({f["metadata"]["projectId"] for f in findings})

    # Files affected
    by_file = defaultdict(list)
    for f in findings:
        by_file[f["metadata"]["filePath"]].append(f)

    # Hot spots: files with 3+ findings
    hot_spots = [
        {
            "path": path,
            "count": len(items),
            "slugs": dict(Counter(i["metadata"]["vulnSlug"] for i in items)),
            "severities": dict(Counter(i["metadata"]["severity"] for i in items)),
        }
        for path, items in by_file.items()
        if len(items) >= 3
    ]
    hot_spots.sort(key=lambda x: -x["count"])

    # Directory aggregation (top-3 path segments)
    def get_dir(path: str, depth: int = 3) -> str:
        parts = path.split("/")[:depth]
        return "/".join(parts)

    by_dir = Counter(get_dir(f["metadata"]["filePath"]) for f in findings)

    # Low-confidence findings (candidates for dismissal review)
    low_conf = [
        {
            "title": f["title"],
            "path": f["metadata"]["filePath"],
            "slug": f["metadata"]["vulnSlug"],
            "severity": f["metadata"]["severity"],
        }
        for f in findings
        if f["metadata"].get("confidence") == "low"
    ]

    result = {
        "total": total,
        "projects": projects,
        "severity_distribution": dict(severity),
        "confidence_distribution": dict(confidence),
        "verdict_distribution": dict(verdicts),
        "top_slugs": dict(slugs.most_common(10)),
        "hot_spots": hot_spots[:15],  # top 15
        "top_directories": dict(by_dir.most_common(10)),
        "low_confidence_findings": low_conf,
        "files_affected": len(by_file),
        "avg_findings_per_file": round(total / max(len(by_file), 1), 2),
    }

    if sidecar is not None:
        eff = state_mod.build_effective_map(findings, sidecar)
        sessions = sidecar.get("sessions", [])
        result["effective_state_distribution"] = dict(Counter(eff.values()))
        result["session_count"] = len(sessions)
        result["last_session"] = sessions[-1] if sessions else None

    return result


def print_human(stats: dict) -> None:
    print(f"=== DEEPSEC FINDINGS STATS ===")
    print(f"Total findings: {stats['total']}")
    print(f"Projects: {', '.join(stats['projects'])}")
    print()

    print("Severity distribution:")
    for sev, n in sorted(
        stats["severity_distribution"].items(),
        key=lambda x: -x[1],
    ):
        print(f"  {sev}: {n}")
    print()

    print("Verdict distribution (revalidation):")
    for v, n in stats["verdict_distribution"].items():
        print(f"  {v}: {n}")
    print()

    if "effective_state_distribution" in stats:
        print("Effective state distribution (sidecar + native, sidecar key precedence):")
        for s, n in sorted(
            stats["effective_state_distribution"].items(),
            key=lambda x: -x[1],
        ):
            print(f"  {s}: {n}")
        print()
        last = stats.get("last_session")
        if last:
            print(f"Last session: {last['sessionId']}")
            print(f"  Started:    {last.get('startedAt')}")
            print(f"  Ended:      {last.get('endedAt') or '(open)'}")
            print(f"  Decisions:  {len(last.get('decisions', []))}")
            if last.get("summary"):
                print(f"  Summary:    {last['summary']}")
            print()

    print("Top vulnerability categories:")
    for slug, n in stats["top_slugs"].items():
        print(f"  {slug}: {n}")
    print()

    print(f"Hot spots ({len(stats['hot_spots'])} files with 3+ findings):")
    for hs in stats["hot_spots"][:10]:
        slugs = ", ".join(f"{k}({v})" for k, v in hs["slugs"].items())
        print(f"  {hs['path']}: {hs['count']} findings — {slugs}")
    print()

    print("Top affected directories:")
    for d, n in stats["top_directories"].items():
        print(f"  {d}: {n}")
    print()

    if stats["low_confidence_findings"]:
        print(f"Low-confidence findings ({len(stats['low_confidence_findings'])}):")
        for f in stats["low_confidence_findings"]:
            print(f"  [{f['severity']}] {f['title']}")
            print(f"    Path: {f['path']}")
            print(f"    Slug: {f['slug']}")
    else:
        print("No low-confidence findings.")
    print()

    print(f"Files affected: {stats['files_affected']}")
    print(f"Avg findings per affected file: {stats['avg_findings_per_file']}")


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="stats.py", description=__doc__)
    parser.add_argument("findings", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--state",
        action="store_true",
        help="Include effective_state distribution from sidecar",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override deepsec data directory for sidecar resolution",
    )
    args = parser.parse_args()

    if not args.findings.exists():
        print(f"File not found: {args.findings}", file=sys.stderr)
        sys.exit(1)

    with open(args.findings) as f:
        findings = json.load(f)

    sidecar = None
    if args.state:
        try:
            pid = state_mod.read_project_id(args.findings)
            sidecar_path = state_mod.resolve_sidecar_path(args.findings, args.data_dir)
            sidecar = state_mod.load_sidecar(sidecar_path, pid)
        except (ValueError, FileNotFoundError) as e:
            print(f"warning: --state requested but sidecar load failed: {e}", file=sys.stderr)

    stats = compute_stats(findings, sidecar=sidecar)

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print_human(stats)


if __name__ == "__main__":
    main()
