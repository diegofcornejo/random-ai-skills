#!/usr/bin/env python3
"""
Compute deterministic statistics from a deepsec findings export.

Usage: python3 stats.py <path_to_findings.json> [--json]

Outputs human-readable stats by default, JSON with --json flag.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def compute_stats(findings: list) -> dict:
    """Compute all the stats Level 1 needs."""

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

    return {
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
    if len(sys.argv) < 2:
        print("Usage: stats.py <path_to_findings.json> [--json]", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    output_json = "--json" in sys.argv

    if not Path(path).exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        findings = json.load(f)

    stats = compute_stats(findings)

    if output_json:
        print(json.dumps(stats, indent=2))
    else:
        print_human(stats)


if __name__ == "__main__":
    main()
