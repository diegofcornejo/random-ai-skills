#!/usr/bin/env python3
"""
Redact sensitive details from a findings.json before sharing.

Useful when you want to share a sanitized version of your scan results
(e.g., for getting help on a forum) without exposing exact code paths,
file structures, or exploitation details.

Usage:
  python3 redact.py <input.json> [output.json]

If output not specified, writes to <input>.redacted.json

What gets redacted:
  - filePath: replaced with hashed-but-stable identifier (so groupings still work)
  - lineNumbers: removed
  - description: code snippets removed (kept reasoning)
  - title: kept (so categorization is preserved)
  - metadata.githubUrl, URLs in text: removed
  - assignee, metadata.owners, and the Owners / Top contributors /
    Recent committers sections of the description: removed (names, emails)
  - project name: removed
  - triage reasoning: redacted (priority / exploitability / impact kept)

What's kept:
  - severity, vulnSlug, confidence, revalidation verdict
  - aggregated reasoning (without snippets)
  - title (categorization signal)
"""

import json
import re
import sys
import hashlib
from pathlib import Path


def hash_path(path: str) -> str:
    """Stable hash of a path so groupings still work after redaction."""
    h = hashlib.md5(path.encode()).hexdigest()[:8]
    # Keep top-level dir for context
    parts = path.split("/")
    if len(parts) > 1:
        return f"{parts[0]}/<redacted-{h}>"
    return f"<redacted-{h}>"


# Description sections `deepsec export` fills with people (names, emails, handles).
PEOPLE_SECTIONS = re.compile(
    r"^## (Owners|Top contributors|Recent committers[^\n]*)\n[\s\S]*?(?=^## |\Z)", re.MULTILINE
)


def redact_text(text: str) -> str:
    """Remove people, code snippets, URLs and file paths from descriptive text."""
    text = PEOPLE_SECTIONS.sub("", text)
    text = re.sub(r"^\*\*Project:\*\*.*$", "**Project:** [redacted]", text, flags=re.MULTILINE)
    # Markdown links and bare URLs (repo, org, branch)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email-redacted]", text)
    text = re.sub(r"(?<![\w.])@[A-Za-z0-9-]{2,}", "[handle-redacted]", text)
    # Remove fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "[CODE REDACTED]", text)
    # Remove inline code
    text = re.sub(r"`[^`\n]+`", "[redacted]", text)
    # Remove file path patterns (anything with multiple slashes)
    text = re.sub(r"\b\w+/[\w/]+\.\w+\b", "[path-redacted]", text)
    # Remove line number references
    text = re.sub(r"\bline\s*\d+\b", "[line-redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"\blines\s*[\d,\s\-]+\b", "[lines-redacted]", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def redact_finding(finding: dict) -> dict:
    """Redact a single finding."""
    md = finding.get("metadata", {})

    redacted = {
        "title": finding.get("title", ""),
        "severity": finding.get("severity"),
        "labels": finding.get("labels", []),
        "description": redact_text(finding.get("description", "")),
        "metadata": {
            "projectId": "<redacted-project>",
            "filePath": hash_path(md.get("filePath", "")),
            "severity": md.get("severity"),
            "vulnSlug": md.get("vulnSlug"),
            "confidence": md.get("confidence"),
            "discoveredAt": md.get("discoveredAt"),
            "runId": "<redacted-run>",
        },
    }

    # Preserve revalidation verdict but redact reasoning
    reval = md.get("revalidation")
    if reval:
        redacted["metadata"]["revalidation"] = {
            "verdict": reval.get("verdict"),
            "reasoning": redact_text(reval.get("reasoning", "")),
        }

    triage = md.get("triage")
    if triage:
        redacted["metadata"]["triage"] = {
            k: triage.get(k) for k in ("priority", "exploitability", "impact")
        }
        redacted["metadata"]["triage"]["reasoning"] = redact_text(triage.get("reasoning", ""))

    return redacted


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    input_path = sys.argv[1]
    output_path = (
        sys.argv[2]
        if len(sys.argv) >= 3
        else str(Path(input_path).with_suffix(".redacted.json"))
    )

    if not Path(input_path).exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        findings = json.load(f)

    redacted = [redact_finding(f) for f in findings]

    with open(output_path, "w") as f:
        json.dump(redacted, f, indent=2)

    print(f"✓ Redacted {len(findings)} findings")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")
    print()
    print("Note: groupings by vulnSlug + path-hash are preserved,")
    print("but you cannot map back to original files without the original JSON.")


if __name__ == "__main__":
    main()
