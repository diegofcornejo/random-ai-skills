#!/usr/bin/env python3
"""Normalize raw gh_alerts.py output into a deterministic, secret-free snapshot with priorities.

Usage: snapshot.py RAW.json -o SNAPSHOT.json [--generated-at ISO]
Writes SNAPSHOT.json (sort_keys, indent=2); a one-line JSON summary goes to stdout.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402
from gh_alerts import strip_secrets  # noqa: E402

SCHEMA = 1
SEVERITIES = ("critical", "high", "medium", "low")
SOURCES = ("dependabot", "code_scanning", "secret_scanning")


def _login(v):
    return v.get("login") if isinstance(v, dict) else v


def _severity(v):
    v = (v or "").lower()
    return v if v in SEVERITIES else "unknown"


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def epss_percentile(advisory):
    """EPSS percentile on a 0-100 scale from object-or-list payloads; values <= 1 are fractions."""
    epss = (advisory or {}).get("epss")
    if isinstance(epss, list):
        epss = epss[0] if epss else None
    if not isinstance(epss, dict):
        return None
    for key in ("percentile", "percentage"):
        v = _num(epss.get(key))
        if v is not None:
            return round(v * 100 if v <= 1 else v, 4)
    return None


def _cvss(adv):
    sev = adv.get("cvss_severities") or {}
    for k in ("cvss_v4", "cvss_v3"):
        s = _num((sev.get(k) or {}).get("score"))
        if s:
            return s
    return _num((adv.get("cvss") or {}).get("score")) or None


# Ruling R26: code-scanning rules about credentials point at the line that holds one, so their
# locations are viewed only through secret_redact.py. Matching is deliberately broad (fail closed).
_CREDENTIAL_ID_TERMS = ("hardcoded-credential", "hardcoded-secret", "clear-text", "cleartext", "password",
                        "token", "api-key", "apikey", "secret", "credential", "private-key")
_CREDENTIAL_CWES = ("cwe-798", "cwe-259", "cwe-321", "cwe-312", "cwe-313", "cwe-315", "cwe-532")
_CREDENTIAL_WORDS = ("credential", "password", "secret", "token", "api key", "private key", "clear text",
                     "cleartext")


def credential_rule(rule):
    """True when a code-scanning rule's id, name, CWE tags, or security description concern credentials."""
    rule = rule or {}
    ident = f"{rule.get('id') or ''} {rule.get('name') or ''}".lower()
    tags = [str(t).lower() for t in rule.get("tags") or []]
    if any(term in ident for term in _CREDENTIAL_ID_TERMS):
        return True
    if any(t.endswith(cwe) for t in tags for cwe in _CREDENTIAL_CWES):
        return True
    text = f"{rule.get('description') or ''} {rule.get('full_description') or ''}".lower()
    return "security" in tags and any(word in text for word in _CREDENTIAL_WORDS)


def normalize_alert(source, repo, raw):
    raw = strip_secrets(raw)
    a = {"source": source, "repo": repo, "owner": repo.split("/")[0], "number": raw.get("number"),
         "state": raw.get("state"), "html_url": raw.get("html_url"), "created_at": raw.get("created_at"),
         "priority": None, "band": None}
    if source == "dependabot":
        adv = raw.get("security_advisory") or {}
        vuln = raw.get("security_vulnerability") or {}
        dep = raw.get("dependency") or {}
        pkg = dep.get("package") or {}
        a.update(severity=_severity(adv.get("severity") or vuln.get("severity")),
                 ecosystem=pkg.get("ecosystem"), package=pkg.get("name"), manifest=dep.get("manifest_path"),
                 scope=dep.get("scope"), relationship=dep.get("relationship"), advisory=adv.get("ghsa_id"),
                 cve=adv.get("cve_id"), epss_percentile=epss_percentile(adv), cvss=_cvss(adv),
                 first_patched=(vuln.get("first_patched_version") or {}).get("identifier"),
                 vulnerable_range=vuln.get("vulnerable_version_range"), summary=adv.get("summary"),
                 dismissed_reason=raw.get("dismissed_reason"), dismissed_by=_login(raw.get("dismissed_by")),
                 dismissed_comment=raw.get("dismissed_comment"), dismissed_at=raw.get("dismissed_at"))
    elif source == "code_scanning":
        rule = raw.get("rule") or {}
        inst = raw.get("most_recent_instance") or {}
        loc = inst.get("location") or {}
        a.update(severity=_severity(rule.get("security_severity_level")), rule_id=rule.get("id"),
                 rule_description=rule.get("description"), tool=(raw.get("tool") or {}).get("name"),
                 credential_rule=credential_rule(rule), commit_sha=inst.get("commit_sha"),
                 path=loc.get("path"), start_line=loc.get("start_line"), end_line=loc.get("end_line"),
                 start_column=loc.get("start_column"), end_column=loc.get("end_column"),
                 classifications=sorted(inst.get("classifications") or []),
                 dismissed_reason=raw.get("dismissed_reason"), dismissed_by=_login(raw.get("dismissed_by")),
                 dismissed_comment=raw.get("dismissed_comment"), dismissed_at=raw.get("dismissed_at"))
    elif source == "secret_scanning":
        a.update(severity="critical", secret_type=raw.get("secret_type"),
                 secret_type_display_name=raw.get("secret_type_display_name"), validity=raw.get("validity"),
                 publicly_leaked=bool(raw.get("publicly_leaked")),
                 push_protection_bypassed=bool(raw.get("push_protection_bypassed")),
                 dismissed_reason=raw.get("resolution"), dismissed_by=_login(raw.get("resolved_by")),
                 dismissed_comment=raw.get("resolution_comment"), dismissed_at=raw.get("resolved_at"))
        if a["state"] == "resolved":
            a["state"] = "dismissed"
    else:
        raise ValueError(f"unknown alert source: {source}")
    return a


def _count(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def build_snapshot(raw, generated_at):
    owners = raw.get("owners", [])
    alerts, coverage, pushed = [], [], {}
    for o in owners:
        for r in o.get("repos", []):
            name = r["repo"]
            pushed[name] = r.get("pushed_at")
            cov = r.get("coverage", {})
            coverage.append({"repo": name, "owner": o["owner"], "private": r.get("private"),
                             "archived": r.get("archived"), "pushed_at": r.get("pushed_at"),
                             **{s: cov.get(s, "unavailable") for s in SOURCES}})
            for source in SOURCES:
                for rawalert in r.get("alerts", {}).get(source, []):
                    a = normalize_alert(source, name, rawalert)
                    a["priority"] = score.priority(a, pushed[name], generated_at)
                    a["band"] = score.band(a["priority"])
                    alerts.append(a)
    alerts.sort(key=lambda a: (a["repo"], a["source"], a["number"]))
    coverage.sort(key=lambda c: c["repo"])
    open_alerts = [a for a in alerts if a["state"] == "open"]
    scanned = [c["repo"] for c in coverage if score._has_coverage(c)]
    # Ruling R22: "at zero" needs every source readable; 0 open with a scanner missing is partial.
    full = {c["repo"] for c in coverage if all(c.get(s) == "ok" for s in SOURCES)}
    with_open = {a["repo"] for a in open_alerts}
    clusters = score.build_clusters(alerts, single_repo=len(coverage) == 1)
    snap = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "scope": {"mode": "repo" if len(coverage) == 1 else "portfolio",
                  "owners": sorted(o["owner"] for o in owners),
                  "strategy": {o["owner"]: o.get("strategy") for o in owners}, "host": raw.get("host"),
                  "public_only": sorted(o["owner"] for o in owners if o.get("public_only")),
                  "repos": sorted(c["repo"] for c in coverage)
                  if any(o.get("strategy") == "repo-filter" for o in owners) else []},
        "coverage": coverage,
        "alerts": alerts,
        "clusters": clusters,
        "ranking": score.rank_repos(alerts, coverage),
        "waves": score.build_waves(alerts, clusters),
        "totals": {
            "open": len(open_alerts),
            "closed_known": len(alerts) - len(open_alerts),
            "by_source": _count(a["source"] for a in open_alerts),
            "by_severity": _count(a["severity"] for a in open_alerts),
            "by_band": _count(a["band"] for a in open_alerts),
            "by_owner": _count(a["owner"] for a in open_alerts),
            "repos": {"total": len(coverage), "scanned": len(scanned),
                      "no_coverage": sorted(c["repo"] for c in coverage if not score._has_coverage(c)),
                      "zero_open": sorted(r for r in scanned if r in full and r not in with_open),
                      "zero_open_partial": sorted(r for r in scanned if r not in full and r not in with_open)},
        },
        "methodology": score.METHODOLOGY,
    }
    return strip_secrets(snap)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    ap.add_argument("--generated-at", help="ISO timestamp (default: now, UTC)")
    args = ap.parse_args(argv)
    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        raw = json.loads(args.raw.read_text())
    except (OSError, ValueError) as e:
        print(json.dumps({"error": f"cannot read {args.raw}: {e}"}))
        print(f"error: cannot read {args.raw}: {e}", file=sys.stderr)
        return 1
    snap = build_snapshot(raw, generated_at)
    args.output.write_text(json.dumps(snap, sort_keys=True, indent=2))
    print(json.dumps({"output": str(args.output), "open": snap["totals"]["open"],
                      "closed_known": snap["totals"]["closed_known"], "repos": snap["totals"]["repos"]["total"]},
                     sort_keys=True))
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
