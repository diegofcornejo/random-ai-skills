#!/usr/bin/env python3
"""Diff two snapshots run over run and read snapshot history.

Usage: diff_snapshots.py CURRENT.json [--scope-dir DIR [--today YYYY-MM-DD] | --previous PREV.json] [-o DIFF.json]
With --scope-dir the previous snapshot is the latest run saved before CURRENT's generated_at (an earlier
run of the same day counts); --today names the day folder and compares against earlier days only.
Writes the diff JSON to stdout (and to -o when given); status messages go to stderr.

Diff keys: baseline, reason, totals{prev_open, curr_open, delta, lost_coverage}, closed, new,
dismissed, lost_coverage, repos_reached_zero, repos_reached_zero_partial, clusters. An alert open in
prev and absent now is `closed` only when its repo+source coverage is still `ok`; otherwise it is
listed in `lost_coverage` (missing coverage is never a fix). `delta` is always curr_open - prev_open.
A repo "reaches zero" only when every source is `ok`; one that closed its last open alert with a
scanner missing is listed in `repos_reached_zero_partial` instead.
`clusters` lists keys that were campaigns on either day whose matching open alerts changed; the
counts include alerts of clusters that fell below the 2-repo threshold. `curr_open` also counts the
cluster's alerts hidden by lost coverage (listed again in the entry's `lost_coverage`), because their
state is unknown: a campaign is done only when `curr_open` is 0.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import _cluster_keys  # noqa: E402

SOURCES = ("dependabot", "code_scanning", "secret_scanning")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2})")
RUN_RE = re.compile(r"^\d{6}\.json$")
RUNS_DIR = "runs"
HISTORY_POINTS = 60


def alert_key(a):
    return f"{a['repo']}#{a['source']}#{a['number']}"


def _open(snap):
    return {alert_key(a): a for a in snap.get("alerts", []) if a.get("state") == "open"}


def _all(snap):
    return {alert_key(a): a for a in snap.get("alerts", [])}


def _scope_key(snap):
    # Logins and repo names are case-insensitive on GitHub, so the scope is compared case-insensitively.
    scope = snap.get("scope") or {}
    return (sorted(str(o).lower() for o in scope.get("owners") or []),
            sorted(str(r).lower() for r in scope.get("repos") or []))


def _baseline(reason, curr):
    n = curr.get("totals", {}).get("open", 0)
    return {"baseline": True, "reason": reason,
            "totals": {"prev_open": n, "curr_open": n, "delta": 0, "lost_coverage": 0},
            "closed": [], "new": [], "dismissed": [], "lost_coverage": [],
            "repos_reached_zero": [], "repos_reached_zero_partial": [], "clusters": []}


def _reached_zero(prev, curr, prev_open, curr_open):
    """(full, partial): repos whose open alerts all closed, split by whether every source is `ok`."""
    cov = {c["repo"]: c for c in curr.get("coverage", [])}
    prev_by_repo = {}
    for a in prev_open.values():
        prev_by_repo.setdefault(a["repo"], set()).add(a["source"])
    curr_repos = {a["repo"] for a in curr_open.values()}
    full, partial = [], []
    for repo, sources in prev_by_repo.items():
        c = cov.get(repo)
        if c is None or repo in curr_repos:
            continue
        # Missing coverage is never zero: every source that had alerts must be readable now, and
        # (Ruling R22) the repo reaches zero only when every source is readable.
        if all(c.get(s) == "ok" for s in sources):
            (full if all(c.get(s) == "ok" for s in SOURCES) else partial).append(repo)
    return sorted(full), sorted(partial)


def _open_by_cluster_key(alerts, keys):
    """Open Dependabot alerts per cluster key, counted whether or not the key meets the >= 2-repo threshold."""
    counts = dict.fromkeys(keys, 0)
    for a in alerts:
        if a.get("source") == "dependabot" and a.get("state") == "open":
            for k, _ in _cluster_keys(a):
                if k in counts:
                    counts[k] += 1
    return counts


def _cluster_diff(prev, curr, lost_alerts=()):
    # Movement for every key that was a campaign on either day. A cluster that drops below the
    # 2-repo threshold disappears from curr["clusters"] but its remaining open alerts still count.
    # Ruling R21: alerts hidden by lost coverage are unknown, not fixed, so they count as still open.
    keys = {c["key"] for c in prev.get("clusters", [])} | {c["key"] for c in curr.get("clusters", [])}
    p = _open_by_cluster_key(prev.get("alerts", []), keys)
    q = _open_by_cluster_key(curr.get("alerts", []), keys)
    lost = _open_by_cluster_key(lost_alerts, keys)
    return [{"key": k, "prev_open": p[k], "curr_open": q[k] + lost[k], "lost_coverage": lost[k]}
            for k in sorted(keys) if p[k] != q[k] + lost[k]]


def read_previous(path):
    """(snapshot, None) for a readable previous snapshot, else (None, baseline reason).

    Ruling R28: a corrupt or unreadable previous snapshot gives a baseline with a warning instead of
    blocking every later run.
    """
    if path is None:
        return None, "first_run"
    try:
        prev = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(prev, dict) and isinstance(prev.get("alerts"), list):
            return prev, None
    except (OSError, ValueError):
        pass
    print(f"warning: previous snapshot {path} is unreadable; starting a new baseline", file=sys.stderr)
    return None, "previous_unreadable"


def diff(prev, curr, baseline_reason="first_run"):
    if prev is None:
        return _baseline(baseline_reason or "first_run", curr)
    if _scope_key(prev) != _scope_key(curr):
        return _baseline("owner_set_changed", curr)
    prev_open, curr_open, curr_all = _open(prev), _open(curr), _all(curr)
    cov = {c["repo"]: c for c in curr.get("coverage", [])}
    gone = sorted(k for k in prev_open if k not in curr_open)
    closed, lost = [], []
    for k in gone:
        a = prev_open[k]
        (closed if cov.get(a["repo"], {}).get(a["source"]) == "ok" else lost).append(k)
    dismissed = []
    for k in closed:
        a = curr_all.get(k)
        if a and a.get("state") == "dismissed":
            dismissed.append({"key": k, "by": a.get("dismissed_by"), "reason": a.get("dismissed_reason"),
                              "comment": a.get("dismissed_comment")})
    p, c = len(prev_open), len(curr_open)
    reached, reached_partial = _reached_zero(prev, curr, prev_open, curr_open)
    return {"baseline": False, "reason": None,
            "totals": {"prev_open": p, "curr_open": c, "delta": c - p, "lost_coverage": len(lost)},
            "closed": closed,
            "new": sorted(k for k in curr_open if k not in prev_open),
            "dismissed": dismissed,
            "lost_coverage": lost,
            "repos_reached_zero": reached,
            "repos_reached_zero_partial": reached_partial,
            "clusters": _cluster_diff(prev, curr, [prev_open[k] for k in lost])}


def run_time(generated_at):
    """HHMMSS of a `YYYY-MM-DDTHH:MM:SS…` timestamp (how run files are named), else None."""
    m = TIME_RE.match(str(generated_at or ""))
    return "".join(m.groups()) if m else None


def _points(scope_dir):
    """Every saved run of the scope, oldest first, as (day, time, path).

    A day folder keeps one file per run in `runs/HHMMSS.json` (UTC). A folder written before runs
    were kept has only `snapshot.json`; it counts as one run with time None, sorted first in its day.
    The day comes from the folder name (Ruling R12), never from the file's generated_at.
    """
    scope_dir = Path(scope_dir)
    if not scope_dir.is_dir():
        return []
    points = []
    for d in scope_dir.iterdir():
        if not (d.is_dir() and DATE_RE.match(d.name)):
            continue
        runs = sorted(f for f in (d / RUNS_DIR).glob("*.json") if RUN_RE.match(f.name)) \
            if (d / RUNS_DIR).is_dir() else []
        if runs:
            points += [(d.name, f.name[:6], f) for f in runs]
        elif (d / "snapshot.json").is_file():
            points.append((d.name, None, d / "snapshot.json"))
    return sorted(points, key=lambda p: (p[0], p[1] or ""))


def earlier_than(point, today, now):
    """Whether a (day, time) point is earlier than the run at `today` / `now` (None: the whole day).

    A folder without runs/ has no run time, so it is earlier only when its day is.
    """
    day, time = point
    if now is None or time is None:
        return day < today
    return (day, time) < (today, now)


def find_previous(scope_dir, today, now=None):
    """The latest run saved before this one: an earlier run of the same day when `now` (HHMMSS) is given."""
    earlier = [p for day, time, p in _points(scope_dir) if earlier_than((day, time), today, now)]
    return earlier[-1] if earlier else None


def load_history(scope_dir, limit=HISTORY_POINTS):
    rows = []
    for day, time, path in _points(scope_dir):
        try:
            totals = json.loads(path.read_text())["totals"]
            rows.append({"date": day, "time": time, "open": totals["open"], "by_band": totals.get("by_band", {})})
        except (OSError, ValueError, KeyError, TypeError):
            print(f"warning: skipping unreadable snapshot {path}", file=sys.stderr)
    return rows[-limit:] if limit else rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("current", type=Path)
    ap.add_argument("--scope-dir", type=Path)
    ap.add_argument("--today")
    ap.add_argument("--previous", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    try:
        curr = json.loads(args.current.read_text())
        prev_path, prev, reason = args.previous, None, "first_run"
        if prev_path is not None:  # named explicitly: it must be readable
            prev = json.loads(prev_path.read_text())
        elif args.scope_dir:
            today = args.today or curr["generated_at"][:10]
            now = None if args.today else run_time(curr["generated_at"])
            prev, reason = read_previous(find_previous(args.scope_dir, today, now))
    except (OSError, ValueError, KeyError) as e:
        print(json.dumps({"error": f"cannot read snapshot: {e}"}))
        print(f"error: cannot read snapshot: {e}", file=sys.stderr)
        return 1
    result = diff(prev, curr, reason)
    text = json.dumps(result, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)
    print(f"diff: baseline={result['baseline']} delta={result['totals']['delta']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
