#!/usr/bin/env python3
"""Fetch, snapshot, diff and render a portfolio security report for one or more owners.

Usage: run_portfolio.py --owner X [--owner Y] [--host H] [--out ./security-reports]
                        [--lang en] [--include-archived] [--date YYYY-MM-DD]
Writes OUT/<scope>/<date>/{snapshot.json,diff.json,report.html,summary.txt}; prints the paths as JSON.
The day folder is the UTC date of generated_at; --date pins it (generated_at becomes <date>T09:00:00Z).
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff_snapshots  # noqa: E402
import render_report  # noqa: E402
import snapshot  # noqa: E402
from gh_alerts import fetch_owner  # noqa: E402
from gh_client import DEFAULT_HOST, GhApiError, GhClient  # noqa: E402


def scope_name(owners):
    return "+".join(sorted(o.lower() for o in owners))


def _write_text(path, text):
    """Write atomically, so an interrupted run never leaves a truncated file behind."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_json(path, data):
    _write_text(path, json.dumps(data, sort_keys=True, indent=2))


def valid_date(value):
    """Ruling R28: --date must be a real, zero-padded YYYY-MM-DD (it names the day folder)."""
    if not diff_snapshots.DATE_RE.match(value or ""):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def run(owners, host, out_root, lang, include_archived=False, today=None, client=None):
    client = client or GhClient(host=host)
    if today:
        generated_at = f"{today}T09:00:00Z"
    else:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    folder = generated_at[:10]
    scope_dir = Path(out_root) / scope_name(owners)
    day_dir = scope_dir / folder
    day_dir.mkdir(parents=True, exist_ok=True)
    cache = day_dir / ".cache"

    raw = {"host": host, "owners": [fetch_owner(client, o, include_archived, cache) for o in owners]}
    snap = snapshot.build_snapshot(raw, generated_at)
    prev, reason = diff_snapshots.read_previous(diff_snapshots.find_previous(scope_dir, folder))
    dif = diff_snapshots.diff(prev, snap, reason)

    paths = {"day_dir": day_dir, "snapshot": day_dir / "snapshot.json", "diff": day_dir / "diff.json",
             "report": day_dir / "report.html", "summary": day_dir / "summary.txt"}
    _write_json(paths["snapshot"], snap)
    _write_json(paths["diff"], dif)
    effective = render_report.load_strings(lang)[1]
    if effective != render_report._lang_code(lang):
        print(f"warning: language {lang!r} not available, using {effective}", file=sys.stderr)
    history = diff_snapshots.load_history(scope_dir)
    _write_text(paths["report"], render_report.render_html(snap, dif, history, effective, None, today=folder))
    _write_text(paths["summary"], render_report.render_summary(snap, dif, effective))
    shutil.rmtree(cache, ignore_errors=True)
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--owner", action="append", required=True, metavar="LOGIN")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--out", type=Path, default=Path("./security-reports"))
    ap.add_argument("--lang", default="en")
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    if args.date is not None and not valid_date(args.date):
        print(json.dumps({"error": f"invalid --date {args.date!r}",
                          "hint": "use --date YYYY-MM-DD, zero-padded (e.g. 2026-01-05)"}))
        print(f"error: invalid --date {args.date!r}", file=sys.stderr)
        return 2
    try:
        paths = run(args.owner, args.host, args.out, args.lang, args.include_archived, args.date)
    except GhApiError as e:
        print(json.dumps({"error": e.message, "hint": e.hint or "check gh auth status and the owner name"}))
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(paths, sort_keys=True))
    print(f"wrote {paths['day_dir']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
