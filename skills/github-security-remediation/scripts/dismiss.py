#!/usr/bin/env python3
"""Dismiss (or resolve) one security alert after validating the reason and comment.

Usage: dismiss.py --repo O/N --source dependabot|code_scanning|secret_scanning --number N
                  --reason R --comment TEXT [--host H] [--dry-run]
--dry-run prints the request and makes no API call. Only the main thread should call this,
and only after the user approved the dismissal.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_client import DEFAULT_HOST, GhApiError, GhClient  # noqa: E402

REASONS = {
    "dependabot": {"fix_started", "inaccurate", "no_bandwidth", "not_used", "tolerable_risk"},
    "code_scanning": {"false positive", "won't fix", "used in tests", "mitigated"},
    "secret_scanning": {"false_positive", "wont_fix", "revoked", "used_in_tests"},
}
_PATHS = {"dependabot": "dependabot", "code_scanning": "code-scanning", "secret_scanning": "secret-scanning"}
MAX_COMMENT = 280


def build_request(source, repo, number, reason, comment):
    if source not in REASONS:
        raise ValueError(f"unknown source {source!r}; use one of {sorted(REASONS)}")
    if reason not in REASONS[source]:
        raise ValueError(f"invalid reason {reason!r} for {source}; use one of {sorted(REASONS[source])}")
    if len(comment) > MAX_COMMENT:
        raise ValueError(f"comment is {len(comment)} characters; the limit is {MAX_COMMENT}")
    path = f"repos/{repo}/{_PATHS[source]}/alerts/{int(number)}"
    if source == "secret_scanning":
        return path, {"state": "resolved", "resolution": reason, "resolution_comment": comment}
    return path, {"state": "dismissed", "dismissed_reason": reason, "dismissed_comment": comment}


def _fail(msg, hint):
    print(json.dumps({"error": msg, "hint": hint}))
    print(f"error: {msg}", file=sys.stderr)
    return 2


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--source", required=True, choices=sorted(REASONS))
    ap.add_argument("--number", required=True, type=int)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--comment", required=True)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        path, body = build_request(args.source, args.repo, args.number, args.reason, args.comment)
    except ValueError as e:
        return _fail(str(e), "fix the reason or shorten the comment, then retry")
    if args.dry_run:
        print(json.dumps({"method": "PATCH", "path": path, "body": body, "dry_run": True}, sort_keys=True))
        return 0
    try:
        res = (client or GhClient(host=args.host)).patch(path, body)
    except GhApiError as e:
        return _fail(e.message, e.hint or "check the alert number, repo and token permissions")
    reason = res.get("dismissed_reason") or res.get("resolution") or args.reason
    print(json.dumps({"number": res.get("number", args.number), "state": res.get("state"), "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
