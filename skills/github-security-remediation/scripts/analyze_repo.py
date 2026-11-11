#!/usr/bin/env python3
"""Single-repo security analysis: snapshot plus open Dependabot PRs, repo meta and autofix status.

Usage: analyze_repo.py [--repo OWNER/NAME] [--host H]
Without --repo the repo is detected from the current directory via `gh repo view`.
Read-only (GET and `gh pr list` only); prints JSON to stdout.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snapshot  # noqa: E402
from gh_alerts import _fetch_single_repo  # noqa: E402
from gh_client import DEFAULT_HOST, GhApiError, GhClient  # noqa: E402

PR_FIELDS = "number,title,headRefName,url,mergeable,statusCheckRollup"


def detect_repo(runner=subprocess.run):
    try:
        proc = runner(["gh", "repo", "view", "--json", "nameWithOwner,url"], capture_output=True, text=True)
    except FileNotFoundError:
        raise GhApiError(None, "gh CLI not found", "gh repo view", "Install GitHub CLI: https://cli.github.com")
    if proc.returncode != 0:
        raise GhApiError(None, (proc.stderr or "gh repo view failed").strip(), "gh repo view",
                         "Run inside a GitHub checkout or pass --repo OWNER/NAME (and run: gh auth login)")
    data = json.loads(proc.stdout)
    host = data["url"].split("//", 1)[-1].split("/", 1)[0]
    return host, data["nameWithOwner"]


def analyze(client, repo, generated_at):
    owners = [_fetch_single_repo(client, repo)]
    meta = client.get(f"repos/{repo}")
    snap = snapshot.build_snapshot({"host": client.host, "owners": owners}, generated_at)
    prs = client.run_json(["pr", "list", "-R", repo, "--author", "app/dependabot", "--state", "open",
                           "--json", PR_FIELDS])
    autofix = {}
    for a in snap["alerts"]:
        if a["source"] == "code_scanning" and a["state"] == "open":
            try:
                res = client.get(f"repos/{repo}/code-scanning/alerts/{a['number']}/autofix")
                autofix[str(a["number"])] = res.get("status", "unavailable") if isinstance(res, dict) else "unavailable"
            except GhApiError:
                autofix[str(a["number"])] = "unavailable"
    snap["dependabot_prs"] = prs if isinstance(prs, list) else []
    snap["repo_meta"] = {"private": bool(meta.get("private")), "default_branch": meta.get("default_branch"),
                         "pushed_at": meta.get("pushed_at")}
    snap["autofix"] = autofix
    return snap


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", metavar="OWNER/NAME")
    ap.add_argument("--host", default=None)
    args = ap.parse_args(argv)
    try:
        host, repo = args.host, args.repo
        if not repo:
            det_host, repo = detect_repo()
            host = host or det_host
        client = GhClient(host=host or DEFAULT_HOST)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = analyze(client, repo, generated_at)
    except GhApiError as e:
        print(json.dumps({"error": e.message, "hint": e.hint or "check the repo name and gh auth status"}))
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
