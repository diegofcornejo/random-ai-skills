#!/usr/bin/env python3
"""Fetch GitHub security alerts (Dependabot, code scanning, secret scanning) with per-repo coverage.

Usage: gh_alerts.py (--owner LOGIN ... | --repo OWNER/NAME) [--host H] [--include-archived]
                    [--cache-dir D] -o RAW.json
(--cache-dir is resume state for a single run; use a fresh directory per day.)
Writes {"host", "owners": [...]} to RAW.json; a one-line JSON summary goes to stdout.
"""
import argparse
import json
import os
import sys
import weakref
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_client import DEFAULT_HOST, GhApiError, GhClient  # noqa: E402

SOURCES = ("dependabot", "code_scanning", "secret_scanning")
COVERAGE = ("ok", "not_enabled", "not_licensed", "no_permission", "unavailable")

# source -> (alert path suffix, list of state queries)
_ALERT_QUERIES = {
    "dependabot": ("dependabot/alerts", ["open,dismissed"]),
    "code_scanning": ("code-scanning/alerts", ["open", "dismissed"]),
    "secret_scanning": ("secret-scanning/alerts", ["open", "resolved"]),
}
# source -> security_and_analysis features whose "disabled" status means not enabled
_FEATURES = {
    "dependabot": (),
    "code_scanning": ("advanced_security", "code_security"),
    "secret_scanning": ("secret_scanning",),
}
_LICENSE_MARKERS = ("advanced security", "code security must be enabled", "secret protection")
_DISABLED_MARKERS = ("disabled", "not enabled", "no analysis found")


def strip_secrets(obj):
    """Recursively drop every key named `secret`."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if k != "secret"}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj


def classify_coverage(source, error, security_and_analysis, private):
    if error is None:
        return "ok"
    msg = (error.message or "").lower()
    status = error.status
    if any(m in msg for m in _LICENSE_MARKERS):
        result = "not_licensed" if private else "not_enabled"
    elif any(m in msg for m in _DISABLED_MARKERS):
        result = "not_enabled"
    elif (status == 403 and ("resource not accessible" in msg or "must have admin" in msg)) or (
            status == 404 and (error.message or "").strip().lower() == "not found"):
        result = "no_permission"
    else:
        result = "unavailable"
    if result != "ok" and security_and_analysis:
        for feature in _FEATURES.get(source, ()):
            if (security_and_analysis.get(feature) or {}).get("status") == "disabled":
                return "not_enabled"
    return result


def _is_fatal(e):
    """Errors that are not coverage answers: transport/auth failures and rate limits must propagate."""
    if e.status in (None, 401, 429):
        return True
    return e.status == 403 and "rate limit" in (e.message or "").lower()


def _params(source, state):
    p = {"per_page": 100, "state": state}
    if source == "secret_scanning":
        p["hide_secret"] = "true"
    return p


def _fetch_source(client, base, source):
    suffix, states = _ALERT_QUERIES[source]
    alerts = []
    for state in states:
        alerts.extend(client.get(f"{base}/{suffix}", _params(source, state), paginate=True))
    return strip_secrets(alerts)


def _new_result(meta):
    return {"repo": meta["full_name"], "private": bool(meta.get("private")),
            "archived": bool(meta.get("archived")), "pushed_at": meta.get("pushed_at"),
            "coverage": {}, "http": {}, "alerts": {s: [] for s in SOURCES}}


def fetch_repo(client, repo_meta):
    result = _new_result(repo_meta)
    sa = repo_meta.get("security_and_analysis")
    for source in SOURCES:
        try:
            result["alerts"][source] = _fetch_source(client, f"repos/{repo_meta['full_name']}", source)
            result["coverage"][source] = "ok"
            result["http"][source] = 200
        except GhApiError as e:
            if _is_fatal(e):
                raise
            result["coverage"][source] = classify_coverage(source, e, sa, result["private"])
            result["http"][source] = e.status
    return result


def _org_admin_check(client, org):
    """A callable telling whether the operator is an active admin (owner) of `org`.

    GET /user/memberships/orgs/{org} is called at most once, and only when first needed.
    """
    memo = {}

    def is_admin():
        if "admin" not in memo:
            try:
                m = client.get(f"user/memberships/orgs/{org}") or {}
                memo["admin"] = m.get("role") == "admin" and m.get("state") == "active"
            except GhApiError as e:
                if _is_fatal(e):
                    raise
                memo["admin"] = False
        return memo["admin"]
    return is_admin


def _org_repo(client, meta, org_alerts, is_admin=lambda: False):
    """Build a repo result from org-wide alert lists, probing coverage where the list is empty."""
    name = meta["full_name"]
    result = _new_result(meta)
    sa = meta.get("security_and_analysis")
    for source in SOURCES:
        alerts = org_alerts[source].get(name, [])
        result["alerts"][source] = alerts
        if alerts:
            result["coverage"][source], result["http"][source] = "ok", 200
        elif source == "dependabot":
            try:
                client.get(f"repos/{name}/vulnerability-alerts")
                result["coverage"][source], result["http"][source] = "ok", 204
            except GhApiError as e:
                if _is_fatal(e):
                    raise
                if e.status == 404:
                    # Ruling R27: the probe needs admin read; a security manager may get 404 on
                    # every repo, so 404 means "not enabled" only for an org admin.
                    result["coverage"][source] = "not_enabled" if is_admin() else "unavailable"
                else:
                    result["coverage"][source] = classify_coverage(source, e, sa, result["private"])
                result["http"][source] = e.status
        elif source == "code_scanning":
            try:
                client.get(f"repos/{name}/code-scanning/analyses", {"per_page": 1})
                result["coverage"][source], result["http"][source] = "ok", 200
            except GhApiError as e:
                if _is_fatal(e):
                    raise
                result["coverage"][source] = classify_coverage(source, e, sa, result["private"])
                result["http"][source] = e.status
        else:  # secret scanning: repo metadata is the authority
            status = ((sa or {}).get("secret_scanning") or {}).get("status")
            result["coverage"][source] = {"enabled": "ok", "disabled": "not_enabled"}.get(status, "unavailable")
            result["http"][source] = None
    return result


def _cache_file(cache_dir, full_name):
    return Path(cache_dir) / (full_name.replace("/", "__") + ".json")


def _owner_file(cache_dir, owner):
    # Logins cannot contain "." and repo files are "<owner>__<name>.json", so this never collides.
    return Path(cache_dir) / f"{owner}.__owner__.json"


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None  # missing or truncated: refetch


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=2))
    os.replace(tmp, path)


def _org_alerts(client, org):
    grouped = {}
    for source in SOURCES:
        by_repo = {}
        for a in _fetch_source(client, f"orgs/{org}", source):
            by_repo.setdefault((a.get("repository") or {}).get("full_name"), []).append(a)
        grouped[source] = by_repo
    return grouped


_LOGINS = weakref.WeakKeyDictionary()


def authenticated_login(client):
    """The operator's login from GET /user (one call per client), or None when it cannot be read."""
    if client not in _LOGINS:
        try:
            _LOGINS[client] = (client.get("user") or {}).get("login")
        except GhApiError as e:
            if _is_fatal(e):
                raise
            _LOGINS[client] = None
    return _LOGINS[client]


def _list_repos(client, owner, is_org):
    """(repo metas, public_only). Ruling R25: GET /users/{login}/repos lists public repos only, so the
    operator's own account is listed with GET /user/repos; other user accounts stay public-only."""
    if is_org:
        return client.get(f"orgs/{owner}/repos", {"per_page": 100}, paginate=True), False
    me = authenticated_login(client)
    if me and me.lower() == owner.lower():
        return client.get("user/repos", {"per_page": 100, "affiliation": "owner", "visibility": "all"},
                          paginate=True), False
    return client.get(f"users/{owner}/repos", {"per_page": 100}, paginate=True), True


def fetch_owner(client, owner, include_archived=False, cache_dir=None):
    info = client.get(f"users/{owner}")
    owner = info.get("login") or owner  # Ruling R23: GitHub's spelling of the login, used everywhere
    is_org = info.get("type") == "Organization"
    kind = "org" if is_org else "user"
    metas, public_only = _list_repos(client, owner, is_org)
    if not include_archived:
        metas = [m for m in metas if not m.get("archived")]
    out = {"owner": owner, "type": kind, "strategy": "per-repo", "repos": []}
    if public_only:
        out["public_only"] = True

    # Ruling R24: the owner-level result is cached next to the repos and restored on resume, never
    # inferred. Repo files without valid owner metadata are not trusted (their strategy is unknown).
    saved = _read_json(_owner_file(cache_dir, owner)) if cache_dir else None
    if not (isinstance(saved, dict) and saved.get("owner") == owner and saved.get("type") == kind
            and saved.get("strategy") in ("org-endpoints", "per-repo")):
        saved = None
    cached, todo = {}, []
    for m in metas:
        res = _read_json(_cache_file(cache_dir, m["full_name"])) if saved else None
        if res is not None:
            cached[m["full_name"]] = res
        else:
            todo.append(m)
    if saved:
        out["strategy"] = saved["strategy"]
        if saved.get("fallback"):
            out["fallback"] = saved["fallback"]

    # Ruling R1: try the org endpoints for an org, unless a resumed run already fell back to per-repo
    # (or has nothing left to fetch).
    org_alerts = None
    if is_org and (saved is None or (saved["strategy"] == "org-endpoints" and todo)):
        try:
            org_alerts = _org_alerts(client, owner)
            out["strategy"] = "org-endpoints"
        except GhApiError as e:
            if _is_fatal(e) or e.status not in (403, 404):
                raise
            out["strategy"] = "per-repo"
            out["fallback"] = f"org endpoints failed (HTTP {e.status}): {e.message}"
            print(f"{owner}: org endpoints unavailable, using per-repo", file=sys.stderr)
    if cache_dir:
        _write_json(_owner_file(cache_dir, owner), {k: out[k] for k in ("owner", "type", "strategy", "fallback")
                                                    if k in out})

    is_admin = _org_admin_check(client, owner)
    for m in metas:
        name = m["full_name"]
        if name in cached:
            res = cached[name]
        else:
            res = _org_repo(client, m, org_alerts, is_admin) if org_alerts is not None else fetch_repo(client, m)
            if cache_dir:
                _write_json(_cache_file(cache_dir, name), res)
        out["repos"].append(res)
    return out


def fetch_repos(client, full_names):
    """Owner entries for an explicit repo list (strategy "repo-filter"), grouped by GitHub's owner login.
    Named repos are fetched even when archived: naming one is the request."""
    owners = {}
    for full_name in full_names:
        meta = client.get(f"repos/{full_name}")
        login = (meta.get("owner") or {}).get("login") or meta["full_name"].split("/")[0]
        entry = owners.get(login.lower())
        if entry is None:
            kind = "org" if (meta.get("owner") or {}).get("type") == "Organization" else "user"
            entry = owners[login.lower()] = {"owner": login, "type": kind, "strategy": "repo-filter", "repos": []}
        if all(r["repo"] != meta["full_name"] for r in entry["repos"]):
            entry["repos"].append(fetch_repo(client, meta))
    return [owners[k] for k in sorted(owners)]


def _fetch_single_repo(client, full_name):
    info = client.get(f"users/{full_name.split('/')[0]}")
    meta = client.get(f"repos/{full_name}")
    owner = info.get("login") or meta["full_name"].split("/")[0]
    return {"owner": owner, "type": "org" if info.get("type") == "Organization" else "user",
            "strategy": "per-repo", "repos": [fetch_repo(client, meta)]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--owner", action="append", metavar="LOGIN")
    g.add_argument("--repo", metavar="OWNER/NAME")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--cache-dir", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args(argv)
    client = GhClient(host=args.host)
    try:
        if args.repo:
            owners = [_fetch_single_repo(client, args.repo)]
        else:
            owners = [fetch_owner(client, o, args.include_archived, args.cache_dir) for o in args.owner]
    except GhApiError as e:
        print(json.dumps({"error": e.message, "status": e.status, "path": e.path, "hint": e.hint}))
        print(f"error: {e}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps({"host": args.host, "owners": owners}, sort_keys=True, indent=2))
    print(json.dumps({"output": str(args.output),
                      "owners": [{"owner": o["owner"], "strategy": o["strategy"], "repos": len(o["repos"])}
                                 for o in owners]}))
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
